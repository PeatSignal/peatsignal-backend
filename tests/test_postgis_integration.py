import asyncio
import os
from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_data_parsers import viirs_file  # noqa: F401

from alembic import command
from app.data.groundwater import import_groundwater
from app.data.hotspots import import_hotspots, parse_bbox
from app.models.entities import DataSource, GroundwaterObservation, Hotspot, Station
from app.repositories.monitoring import MonitoringRepository
from app.schemas.common import MonitoringMode

DATASET = Path(__file__).resolve().parents[1] / "dataset"


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL/PostGIS database")
    engine = create_engine(url)
    with engine.connect() as connection:
        database_name = connection.scalar(text("select current_database()"))
    if not database_name.endswith("_test"):
        pytest.fail("Database name must end in _test; migration tests drop domain tables")
    monkeypatch.setenv("DATABASE_URL", url)
    from app.core.config import get_settings

    get_settings.cache_clear()
    configuration = Config("alembic.ini")
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    yield engine
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    engine.dispose()


def test_import_reimport_conflict_rollback_and_spatial_reads(
    database, viirs_file, monkeypatch  # noqa: F811
) -> None:
    with Session(database) as session, session.begin():
        first = import_groundwater(session, DATASET / "mmc1.xlsx")
        second = import_groundwater(session, DATASET / "mmc1.xlsx")
        assert first["rows_inserted"] == 3928
        assert second["rows_inserted"] == 0
        assert session.scalar(select(func.count(Station.id))) == 8
        assert session.scalar(select(func.count(GroundwaterObservation.id))) == 3928
        assert import_hotspots(session, viirs_file)["rows_inserted"] == 2
        assert import_hotspots(session, viirs_file)["rows_inserted"] == 0
        assert session.scalar(select(func.count(Hotspot.id))) == 2

    with Session(database) as session:
        source_count = session.scalar(select(func.count(DataSource.id)))
    invalid_file = viirs_file.parent / "viirs-snpp_invalid.csv"
    invalid_file.write_text(viirs_file.read_text().replace("0055", "9999"), encoding="utf-8")
    with pytest.raises(ValueError), Session(database) as session, session.begin():
        import_hotspots(session, invalid_file)
    with Session(database) as session:
        assert session.scalar(select(func.count(DataSource.id))) == source_count

    # Fail during COPY, after the source/import-run have been written in the transaction.
    from app.data import hotspots as hotspot_module

    new_file = viirs_file.parent / "viirs-snpp_copy_failure.csv"
    new_file.write_text(viirs_file.read_text().replace("0055", "0056"), encoding="utf-8")
    original_iterator = hotspot_module.iter_hotspots
    calls = 0

    def fail_during_copy(*args, **kwargs):
        nonlocal calls
        calls += 1
        for index, row in enumerate(original_iterator(*args, **kwargs)):
            if calls == 2 and index == 1:
                raise ValueError("simulated source failure during COPY")
            yield row

    with monkeypatch.context() as patch:
        patch.setattr(hotspot_module, "iter_hotspots", fail_during_copy)
        with pytest.raises(ValueError), Session(database) as session, session.begin():
            import_hotspots(session, new_file)
    with Session(database) as session:
        assert session.scalar(select(func.count(DataSource.id))) == source_count
        assert session.scalar(select(func.count(Hotspot.id))) == 2

    async def check_reads():
        async_url = database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql+psycopg_async://"
        )
        async_engine = create_async_engine(async_url)
        try:
            async with async_sessionmaker(async_engine)() as session:
                repository = MonitoringRepository(session)
                stations = await repository.list_stations()
                assert len(stations) == 8
                assert all(s.latitude is None and s.longitude is None for s in stations)
                from uuid import UUID

                brg6 = next(s for s in stations if s.code == "BRG6")
                assert brg6.period_start == date(2018, 4, 11)
                assert brg6.period_end == date(2019, 10, 7)
                assert brg6.source == "mmc1.xlsx"
                observations = await repository.list_groundwater(
                    UUID(brg6.id), date_from=date(2019, 1, 1), date_to=date(2019, 1, 3),
                    mode=MonitoringMode.HISTORICAL_REPLAY,
                )
                assert [o.observed_date.day for o in observations] == [1, 2, 3]
                assert await repository.list_groundwater(
                    UUID(brg6.id), date_from=None, date_to=None,
                    mode=MonitoringMode.CURRENT_MONITORING,
                ) == []
                page = await repository.list_hotspots(
                    date_from=date(2019, 1, 1), date_to=date(2019, 1, 1),
                    bbox=parse_bbox("102,-1.5,104,0"), satellite="N",
                    source_product="VIIRS_SNPP_HISTORICAL",
                    mode=MonitoringMode.HISTORICAL_REPLAY, limit=1, offset=0,
                )
                assert page.total == 1
                assert page.items[0].longitude == 103
                session.add(Station(code="EMPTY", region=None))
                await session.flush()
                empty = next(s for s in await repository.list_stations() if s.code == "EMPTY")
                assert empty.period_start is None and empty.period_end is None
                assert empty.source is None
        finally:
            await async_engine.dispose()

    asyncio.run(check_reads())
