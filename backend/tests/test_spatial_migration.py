from pathlib import Path


def test_spatial_migration_declares_postgis_location_point_and_index() -> None:
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0024_postgis_location_points.py"
    ).read_text(encoding="utf-8")

    assert 'CREATE EXTENSION IF NOT EXISTS postgis' in migration
    assert "geography(POINT, 4326)" in migration
    assert "ST_MakePoint" in migration
    assert "USING GIST (location_geog)" in migration
