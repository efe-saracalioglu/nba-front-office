from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CapStatus(StrEnum):
    UNDER_CAP = "under_cap"
    OVER_CAP = "over_cap"
    OVER_TAX = "over_tax"
    OVER_FIRST_APRON = "over_first_apron"
    OVER_SECOND_APRON = "over_second_apron"


class Player(BaseModel):
    player_id: int
    name: str
    team: str
    salary: int | None
    is_two_way: bool = False
    signed_on: date | None = None
    acquired_by_trade_on: date | None = None


class PickAsset(BaseModel):
    asset_id: str
    year: int
    round: int
    owner: str
    original: str | None
    kind: Literal["own", "acquired", "swap_right", "conditional"]
    description: str = ""
    protection: str | None = None

    @property
    def counts_as_pick(self) -> bool:
        return self.kind in ("own", "acquired")


class TeamState(BaseModel):
    team: str
    players: list[Player] = Field(default_factory=list)
    dead_money: int = 0

    @property
    def payroll(self) -> int:
        return self.dead_money + sum(p.salary or 0 for p in self.players if not p.is_two_way)

    @property
    def standard_roster(self) -> int:
        return sum(not p.is_two_way for p in self.players)

    @property
    def two_way_roster(self) -> int:
        return sum(p.is_two_way for p in self.players)


class TradeLeg(BaseModel):
    from_team: str
    to_team: str
    players: list[int] = Field(default_factory=list)
    picks: list[str] = Field(default_factory=list)
    cash: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _distinct_teams(self) -> TradeLeg:
        if self.from_team == self.to_team:
            raise ValueError("a leg must move assets between two different teams")
        return self


class Trade(BaseModel):
    legs: list[TradeLeg] = Field(min_length=1)
    trade_date: date

    @property
    def teams(self) -> list[str]:
        return sorted({t for leg in self.legs for t in (leg.from_team, leg.to_team)})


class RuleViolation(BaseModel):
    code: str
    message: str
    team: str | None = None
    severity: Literal["error", "warning"] = "error"
    details: dict = Field(default_factory=dict)


class TeamTradeSummary(BaseModel):
    team: str
    payroll_before: int
    payroll_after: int
    status_before: CapStatus
    status_after: CapStatus
    outgoing_salary: int
    incoming_salary: int
    max_incoming_salary: int | None
    traded_player_exception: int
    standard_roster_before: int
    standard_roster_after: int
    two_way_after: int
    hard_cap: Literal["first_apron", "second_apron"] | None = None


class TradeVerdict(BaseModel):
    valid: bool
    violations: list[RuleViolation]
    warnings: list[RuleViolation]
    teams: list[TeamTradeSummary]

    def explain(self) -> str:
        lines = ["VALID" if self.valid else "INVALID"]
        lines += [f"[{v.code}] {v.message}" for v in self.violations]
        lines += [f"(warning) [{w.code}] {w.message}" for w in self.warnings]
        return "\n".join(lines)
