from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SAMPLE_DB = DATA_DIR / "sample" / "warehouse_sample.duckdb"
SCHEMA_SQL = DATA_DIR / "schema.sql"

FIRST_SEASON = "2010-11"
LAST_COMPLETED_SEASON = "2025-26"
CURRENT_SEASON = "2026-27"


def default_db_path() -> Path:
    return Path(os.environ.get("FRONT_OFFICE_DB", DATA_DIR / "warehouse.duckdb"))


def season_label(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def season_end_year(label: str) -> int:
    return int(label[:4]) + 1


def season_range(first: str, last: str) -> list[str]:
    return [season_label(y) for y in range(season_end_year(first), season_end_year(last) + 1)]


TEAMS: dict[int, tuple[str, str, str, str]] = {
    1610612737: ("ATL", "ATL", "East", "Southeast"),
    1610612738: ("BOS", "BOS", "East", "Atlantic"),
    1610612751: ("BKN", "BRK", "East", "Atlantic"),
    1610612766: ("CHA", "CHO", "East", "Southeast"),
    1610612741: ("CHI", "CHI", "East", "Central"),
    1610612739: ("CLE", "CLE", "East", "Central"),
    1610612742: ("DAL", "DAL", "West", "Southwest"),
    1610612743: ("DEN", "DEN", "West", "Northwest"),
    1610612765: ("DET", "DET", "East", "Central"),
    1610612744: ("GSW", "GSW", "West", "Pacific"),
    1610612745: ("HOU", "HOU", "West", "Southwest"),
    1610612754: ("IND", "IND", "East", "Central"),
    1610612746: ("LAC", "LAC", "West", "Pacific"),
    1610612747: ("LAL", "LAL", "West", "Pacific"),
    1610612763: ("MEM", "MEM", "West", "Southwest"),
    1610612748: ("MIA", "MIA", "East", "Southeast"),
    1610612749: ("MIL", "MIL", "East", "Central"),
    1610612750: ("MIN", "MIN", "West", "Northwest"),
    1610612740: ("NOP", "NOP", "West", "Southwest"),
    1610612752: ("NYK", "NYK", "East", "Atlantic"),
    1610612760: ("OKC", "OKC", "West", "Northwest"),
    1610612753: ("ORL", "ORL", "East", "Southeast"),
    1610612755: ("PHI", "PHI", "East", "Atlantic"),
    1610612756: ("PHX", "PHO", "West", "Pacific"),
    1610612757: ("POR", "POR", "West", "Northwest"),
    1610612758: ("SAC", "SAC", "West", "Pacific"),
    1610612759: ("SAS", "SAS", "West", "Southwest"),
    1610612761: ("TOR", "TOR", "East", "Atlantic"),
    1610612762: ("UTA", "UTA", "West", "Northwest"),
    1610612764: ("WAS", "WAS", "East", "Southeast"),
}

BBREF_TO_TEAM_ID = {bbref: tid for tid, (_, bbref, _, _) in TEAMS.items()}
