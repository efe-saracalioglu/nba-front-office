from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from data.config import CURRENT_SEASON, ROOT

SEASONS_DIR = ROOT / "config" / "seasons"


class CalendarConfig(BaseModel):
    league_year_start: date
    league_year_end: date
    regular_season_start: date
    trade_deadline: date


class TradeConfig(BaseModel):
    matching_cushion: int
    matching_bracket: int
    apron_matching_pct: float
    cash_limit: int
    aggregation_wait_days: int


class SigningConfig(BaseModel):
    offseason_start: date
    offseason_trade_date: date
    wait_months: int


class RosterConfig(BaseModel):
    offseason_max_standard: int
    max_standard: int
    min_standard: int
    temporary_min_standard: int
    max_two_way: int


class DraftConfig(BaseModel):
    first_tradable_year: int
    last_tradable_year: int


class SeasonConfig(BaseModel):
    season: str
    sources: list[str] = []
    salary_cap: int
    minimum_team_salary: int
    minimum_salary: int
    luxury_tax: int
    first_apron: int
    second_apron: int
    calendar: CalendarConfig
    trade: TradeConfig
    signing: SigningConfig
    roster: RosterConfig
    draft: DraftConfig


@cache
def load_season(season: str = CURRENT_SEASON, directory: Path = SEASONS_DIR) -> SeasonConfig:
    raw = yaml.safe_load((directory / f"{season}.yaml").read_text(encoding="utf-8"))
    return SeasonConfig.model_validate(raw)
