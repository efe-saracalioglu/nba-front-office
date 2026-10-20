from __future__ import annotations

from dataclasses import dataclass, field

from rules.models import CapStatus, PickAsset, Player, TeamState, Trade
from rules.season import SeasonConfig
from rules.state import LeagueState


def cap_status(payroll: int, season: SeasonConfig) -> CapStatus:
    if payroll > season.second_apron:
        return CapStatus.OVER_SECOND_APRON
    if payroll > season.first_apron:
        return CapStatus.OVER_FIRST_APRON
    if payroll > season.luxury_tax:
        return CapStatus.OVER_TAX
    if payroll > season.salary_cap:
        return CapStatus.OVER_CAP
    return CapStatus.UNDER_CAP


@dataclass
class TeamFlow:
    team: str
    state: TeamState
    out_players: list[Player] = field(default_factory=list)
    in_players: list[Player] = field(default_factory=list)
    out_picks: list[PickAsset] = field(default_factory=list)
    in_picks: list[PickAsset] = field(default_factory=list)
    cash_sent: int = 0
    cash_received: int = 0

    @staticmethod
    def _cap_salary(players: list[Player]) -> int:
        return sum(p.salary or 0 for p in players if not p.is_two_way)

    @property
    def out_salary(self) -> int:
        return self._cap_salary(self.out_players)

    @property
    def in_salary(self) -> int:
        return self._cap_salary(self.in_players)

    @property
    def payroll_before(self) -> int:
        return self.state.payroll

    @property
    def payroll_after(self) -> int:
        return self.payroll_before - self.out_salary + self.in_salary

    @property
    def salaried_out_count(self) -> int:
        return sum(1 for p in self.out_players if not p.is_two_way and (p.salary or 0) > 0)

    @property
    def aggregates(self) -> bool:
        return self.salaried_out_count >= 2 and self.in_salary > 0

    @property
    def standard_after(self) -> int:
        moved = sum(not p.is_two_way for p in self.in_players) - sum(
            not p.is_two_way for p in self.out_players
        )
        return self.state.standard_roster + moved

    @property
    def two_way_after(self) -> int:
        moved = sum(p.is_two_way for p in self.in_players) - sum(
            p.is_two_way for p in self.out_players
        )
        return self.state.two_way_roster + moved


@dataclass
class TradeContext:
    trade: Trade
    league: LeagueState
    flows: dict[str, TeamFlow]
    pick_owners_after: dict[str, str]

    @property
    def season(self) -> SeasonConfig:
        return self.league.season
