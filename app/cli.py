import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from app.data.groundwater import (
    audit_groundwater,
    import_groundwater,
    write_groundwater_outputs,
)
from app.data.hotspots import audit_hotspots, import_hotspots, parse_bbox
from app.db.session import SessionLocal


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_hotspot_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="date_from", type=iso_date)
    parser.add_argument("--to", dest="date_to", type=iso_date)
    parser.add_argument("--bbox", type=parse_bbox, metavar="WEST,SOUTH,EAST,NORTH")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gambutops")
    commands = parser.add_subparsers(dest="command", required=True)

    audit_gwt = commands.add_parser("audit-gwt", help="Audit and normalize mmc1.xlsx")
    audit_gwt.add_argument("file", type=Path)
    audit_gwt.add_argument("--output-dir", type=Path, default=Path("var/audits"))

    import_gwt = commands.add_parser("import-gwt", help="Import audited GWT observations")
    import_gwt.add_argument("file", type=Path)
    import_gwt.add_argument("--apply", action="store_true")

    audit_viirs = commands.add_parser("audit-hotspots", help="Audit VIIRS CSV files")
    audit_viirs.add_argument("files", nargs="+", type=Path)
    audit_viirs.add_argument("--output", type=Path)
    _add_hotspot_filters(audit_viirs)

    import_viirs = commands.add_parser("import-hotspots", help="Import VIIRS CSV files")
    import_viirs.add_argument("files", nargs="+", type=Path)
    import_viirs.add_argument("--apply", action="store_true")
    import_viirs.add_argument("--allow-full-dataset", action="store_true")
    _add_hotspot_filters(import_viirs)
    sync = commands.add_parser("sync-hotspots", help="Sync latest NASA FIRMS hotspots")
    sync.add_argument("--area", required=True, choices=["batanghari", "kubu-raya", "indonesia"])
    sync.add_argument("--product", required=True, choices=["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"])
    sync.add_argument("--days", type=int, default=3, choices=range(1, 6))
    sync.add_argument("--apply", action="store_true")
    train_gwt = commands.add_parser(
        "train-gwt", help="Train and evaluate the historical GWT +1 day experiment"
    )
    train_gwt.add_argument("file", type=Path)
    train_gwt.add_argument(
        "--stations", nargs="+", default=["BRG6", "BRG3"], metavar="CODE"
    )
    train_gwt.add_argument("--output-dir", type=Path, default=Path("var/ml"))
    return parser


def _validate_dates(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.date_from and args.date_to and args.date_from > args.date_to:
        parser.error("--from must be on or before --to")


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "train-gwt":
        from app.ml.pipeline import (
            train_station_experiment,
            write_experiment_result,
            write_model_artifact,
        )

        audit = audit_groundwater(args.file)
        source_sha256 = audit.report["source"]["sha256"]
        results = []
        for station in args.stations:
            model, result = train_station_experiment(audit.records, station, source_sha256)
            artifact_path = write_model_artifact(model, result, args.output_dir)
            output_path = args.output_dir / f"{station.strip().lower()}.metrics.json"
            write_experiment_result(result, output_path)
            results.append(
                {
                    **result,
                    "predictions": [],
                    "output": output_path.as_posix(),
                    "artifact": artifact_path.as_posix(),
                }
            )
        _print_json({"experiments": results})
        return 0

    if args.command == "sync-hotspots":
        from app.core.config import get_settings
        from app.core.security import DEMO_COORDINATOR_ID
        from app.data.firms_client import SYNC_AREAS, FirmsClient, FirmsError
        from app.data.firms_sync import FirmsSyncService
        from app.db.session import async_engine
        from app.schemas.firms import SyncRequest

        request = SyncRequest(
            area_id=args.area, source_product=args.product, day_range=args.days
        )
        if not args.apply:
            bbox = SYNC_AREAS[args.area]
            _print_json({
                "dry_run": True, **request.model_dump(),
                "bbox": [bbox.west, bbox.south, bbox.east, bbox.north],
                "key_configured": bool(get_settings().firms_map_key),
                "message": "Run with --apply to contact NASA and store data",
            })
            return 0

        async def perform():
            try:
                service = FirmsSyncService(
                    async_engine, FirmsClient(get_settings().firms_map_key)
                )
                return await service.sync(request, DEMO_COORDINATOR_ID)
            finally:
                await async_engine.dispose()

        try:
            _print_json(asyncio.run(perform()).model_dump(mode="json"))
            return 0
        except FirmsError as exc:
            _print_json({"error_code": exc.code, "detail": exc.detail,
                         "retry_after": exc.retry_after})
            return 1

    if args.command == "audit-gwt":
        audit = audit_groundwater(args.file)
        output_dir: Path = args.output_dir
        audit_path = output_dir / f"{args.file.stem}.audit.json"
        normalized_path = output_dir / f"{args.file.stem}.normalized.csv"
        write_groundwater_outputs(audit, audit_path, normalized_path)
        _print_json(
            {
                "audit": audit.report,
                "audit_json": audit_path.as_posix(),
                "normalized_csv": normalized_path.as_posix(),
            }
        )
        return 0

    if args.command == "import-gwt":
        if not args.apply:
            _print_json(
                {
                    "dry_run": True,
                    "audit": audit_groundwater(args.file).report,
                    "message": "Run again with --apply to write to PostgreSQL",
                }
            )
            return 0
        with SessionLocal.begin() as session:
            result = import_groundwater(session, args.file)
        _print_json(result)
        return 0

    if args.command in {"audit-hotspots", "import-hotspots"}:
        _validate_dates(parser, args)
        if args.command == "import-hotspots" and args.apply and not (
            args.date_from or args.date_to or args.bbox or args.allow_full_dataset
        ):
            parser.error(
                "a date filter, --bbox, or --allow-full-dataset is required for hotspot import"
            )
        reports = [
            audit_hotspots(
                path,
                date_from=args.date_from,
                date_to=args.date_to,
                bbox=args.bbox,
            )
            for path in args.files
        ]
        if args.command == "audit-hotspots":
            payload = {"files": reports, "total_rows": sum(report["rows"] for report in reports)}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            _print_json(payload)
            return 0

        if not args.apply:
            _print_json(
                {
                    "dry_run": True,
                    "files": reports,
                    "message": "Run again with --apply to write to PostgreSQL",
                }
            )
            return 0
        results = []
        with SessionLocal.begin() as session:
            for path in args.files:
                results.append(
                    import_hotspots(
                        session,
                        path,
                        date_from=args.date_from,
                        date_to=args.date_to,
                        bbox=args.bbox,
                    )
                )
        _print_json({"files": results})
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    return run(parser.parse_args(argv), parser)


if __name__ == "__main__":
    raise SystemExit(main())
