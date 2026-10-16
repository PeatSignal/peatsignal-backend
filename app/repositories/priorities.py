import hashlib
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.firms_client import AREAS
from app.data.priority_rules import RULE_CONFIG, RULE_VERSION, evaluate
from app.models.entities import (
    DataSource,
    FieldReport,
    GroundwaterObservation,
    Hotspot,
    InspectionTask,
    PriorityAssessment,
    Station,
    TaskStatusHistory,
)
from app.schemas.priority import PriorityAssessment as AssessmentResponse

REGIONS = {"batanghari": "Batanghari", "kubu-raya": "Kubu Raya"}


class PriorityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def assess(self, mode: str, as_of: datetime, area_id: str) -> AssessmentResponse:
        box = AREAS[area_id]
        window = RULE_CONFIG["window_days"]
        freshness = RULE_CONFIG["gwt_freshness_days"]
        start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        start -= timedelta(days=window - 1)
        groundwater = (await self.session.execute(
            select(GroundwaterObservation, Station.code, DataSource.sha256)
            .join(Station, Station.id == GroundwaterObservation.station_id)
            .join(DataSource, DataSource.id == GroundwaterObservation.source_id)
            .where(
                Station.region == REGIONS[area_id], GroundwaterObservation.mode == mode,
                GroundwaterObservation.observed_date <= as_of.date(),
                GroundwaterObservation.observed_date >= (start - timedelta(days=freshness)).date(),
            ).order_by(Station.code, GroundwaterObservation.observed_date)
        )).all()
        grouped = {}
        for observation, code, sha256 in groundwater:
            grouped.setdefault(code, []).append({
                "id": str(observation.id), "date": observation.observed_date.isoformat(),
                "value_m": observation.gwt_m, "quality": observation.quality_flag,
                "source_sha256": sha256,
            })
        trends = []
        for code, rows in grouped.items():
            end = datetime.fromisoformat(rows[-1]["date"]).date()
            seven = [r for r in rows if r["date"] >= (end - timedelta(days=window - 1)).isoformat()]
            if ((as_of.date() - end).days <= freshness and len(seven) == window
                    and all(r["quality"] == "VALID" and r["value_m"] is not None for r in seven)):
                trends.append({"station": code, "delta_m": round(
                    seven[-1]["value_m"] - seven[0]["value_m"], 6
                ), "observations": seven})
        query = select(Hotspot, DataSource.sha256).join(DataSource).where(
            Hotspot.mode == mode, Hotspot.acquired_at >= start, Hotspot.acquired_at <= as_of,
            Hotspot.quality_flag == "VALID",
            func.ST_Intersects(Hotspot.geom, func.ST_MakeEnvelope(
                box.west, box.south, box.east, box.north, 4326
            )),
        ).order_by(Hotspot.acquired_at, Hotspot.id)
        if mode == "CURRENT_MONITORING":
            # Corrected NRT records retrieved later cannot be used in an earlier assessment.
            query = query.where(Hotspot.last_synced_at <= as_of)
        hotspots = []
        hotspot_ids = []
        for hotspot, sha256 in (await self.session.execute(query)).all():
            hotspot_ids.append(hotspot.id)
            hotspots.append({"id": str(hotspot.id), "acquired_at": hotspot.acquired_at.isoformat(),
                             "source_sha256": sha256, "reviewed": False})
        reports = []
        verification_reports = []
        if hotspot_ids:
            # Reconstruct task state at cutoff, never trust today's mutable task/hotspot status.
            latest_status = select(TaskStatusHistory.to_status).where(
                TaskStatusHistory.task_id == InspectionTask.id,
                TaskStatusHistory.changed_at <= as_of,
            ).order_by(TaskStatusHistory.changed_at.desc(), TaskStatusHistory.id.desc()).limit(1)
            results = (await self.session.execute(
                select(FieldReport, InspectionTask.hotspot_id).join(InspectionTask)
                .where(InspectionTask.hotspot_id.in_(hotspot_ids),
                       InspectionTask.created_at <= as_of,
                       latest_status.scalar_subquery() == "VERIFIED",
                       FieldReport.created_at <= as_of,
                       FieldReport.observed_at >= start, FieldReport.observed_at <= as_of)
                .order_by(FieldReport.id)
            )).all()
            reviewed = set()
            for report, hotspot_id in results:
                # Simulation reports must not promote a real current-monitoring assessment.
                if mode == "CURRENT_MONITORING" and report.is_simulation:
                    continue
                reviewed.add(str(hotspot_id))
                verification_reports.append({
                    "id": str(report.id), "task_id": str(report.task_id),
                    "hotspot_id": str(hotspot_id), "result": report.result,
                    "observed_at": report.observed_at.isoformat(),
                    "created_at": report.created_at.isoformat(),
                    "is_simulation": report.is_simulation,
                })
                if report.result in {"ACTIVE_FIRE_FOUND", "BURN_SCAR_FOUND"}:
                    reports.append({"id": str(report.id), "hotspot_id": str(hotspot_id),
                                    "observed_at": report.observed_at.isoformat(),
                                    "result": report.result, "is_simulation": report.is_simulation})
            for hotspot in hotspots:
                hotspot["reviewed"] = hotspot["id"] in reviewed
        snapshot = {
            "area_id": area_id, "region": REGIONS[area_id],
            "bbox": [box.west, box.south, box.east, box.north],
            "boundary_source": "DEMO bounding box, bukan batas administratif resmi",
            "window_start": start.isoformat(), "window_end": as_of.isoformat(),
            "rule_config": RULE_CONFIG, "gwt_scope": "REGIONAL_NOT_LOCAL",
            "groundwater_observations": grouped, "gwt_trends": trends,
            "hotspots": hotspots, "supporting_reports": reports,
            "verification_reports": verification_reports,
            "absence_is_not_safety": True,
        }
        result = evaluate(snapshot)
        material = {"mode": mode, "as_of": as_of.isoformat(), "snapshot": snapshot,
                    "rule_version": RULE_VERSION}
        digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        assessment_id = uuid.uuid5(uuid.NAMESPACE_URL, "gambutops:priority:" + digest)
        await self.session.execute(insert(PriorityAssessment).values(
            id=assessment_id, mode=mode, as_of=as_of, priority=result["priority"],
            explanation=result["explanation"], reasons_json=result["reason_codes"],
            missing_inputs_json=result["missing_inputs"], inputs_json=snapshot,
            recommended_actions_json=result["recommended_actions"], rule_version=RULE_VERSION,
        ).on_conflict_do_nothing(index_elements=[PriorityAssessment.id]))
        return AssessmentResponse(
            id=str(assessment_id), mode=mode, as_of=as_of, area_id=area_id,
            input_snapshot=snapshot, rule_version=RULE_VERSION, **result,
        )
