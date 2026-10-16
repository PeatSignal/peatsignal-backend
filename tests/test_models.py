from app.db.base import Base
from app.models import entities  # noqa: F401


def test_foundation_metadata_contains_all_required_tables() -> None:
    assert {
        "data_sources",
        "stations",
        "groundwater_observations",
        "hotspots",
        "priority_assessments",
        "inspection_tasks",
        "field_reports",
        "users",
        "task_status_history",
    } <= set(Base.metadata.tables)


def test_station_coordinates_require_provenance_at_database_level() -> None:
    constraint_names = {
        constraint.name for constraint in Base.metadata.tables["stations"].constraints
    }
    assert "ck_stations_coordinates_require_source" in constraint_names

