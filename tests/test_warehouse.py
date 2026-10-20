import duckdb
import pandas as pd
import pytest

from data import config, db, quality


def test_season_helpers():
    assert config.season_label(2025) == "2024-25"
    assert config.season_label(2000) == "1999-00"
    assert config.season_end_year("2024-25") == 2025
    assert config.season_range("2022-23", "2024-25") == ["2022-23", "2023-24", "2024-25"]


def test_team_reference_is_complete():
    assert len(config.TEAMS) == 30
    assert len(config.BBREF_TO_TEAM_ID) == 30
    assert config.BBREF_TO_TEAM_ID["PHO"] == 1610612756


def test_replace_rows_is_idempotent():
    con = db.connect(":memory:")
    db.create_schema(con)
    df = pd.DataFrame({"team_id": [1, 2], "season": ["2024-25"] * 2, "gp": [82, 82], "w": [50, 32]})
    for _ in range(2):
        db.replace_rows(con, "team_season_stats", df, "season = '2024-25'")
    assert con.execute("SELECT count(*) FROM team_season_stats").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM etl_runs").fetchone()[0] == 2


def test_replace_rows_rolls_back_on_error():
    con = db.connect(":memory:")
    db.create_schema(con)
    good = pd.DataFrame({"team_id": [1], "season": ["2024-25"]})
    db.replace_rows(con, "team_season_stats", good)
    bad = pd.DataFrame({"team_id": [None], "season": ["2024-25"]})
    with pytest.raises(duckdb.ConstraintException):
        db.replace_rows(con, "team_season_stats", bad)
    assert con.execute("SELECT count(*) FROM team_season_stats").fetchone()[0] == 1


@pytest.fixture(scope="module")
def sample_con():
    if not config.SAMPLE_DB.exists():
        pytest.skip("sample warehouse not built (python -m data.make_sample)")
    con = db.connect(config.SAMPLE_DB, read_only=True)
    yield con
    con.close()


def test_sample_passes_quality_checks(sample_con):
    assert quality.run_checks(sample_con) == []


def test_sample_two_way_players_are_flagged(sample_con):
    per_team = sample_con.execute(
        "SELECT max(n) FROM (SELECT count(*) n FROM rosters WHERE is_two_way GROUP BY team_id)"
    ).fetchone()[0]
    assert 1 <= per_team <= 3
