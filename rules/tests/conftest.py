from __future__ import annotations

import itertools
from datetime import date

import pytest

from rules.engine import validate_trade
from rules.models import PickAsset, Player, TeamState, Trade, TradeLeg, TradeVerdict
from rules.season import load_season
from rules.state import LeagueState

SEASON = load_season("2026-27")
CAP, TAX, APRON1, APRON2 = (
    SEASON.salary_cap,
    SEASON.luxury_tax,
    SEASON.first_apron,
    SEASON.second_apron,
)
IN_SEASON = date(2026, 11, 1)
_ids = itertools.count(10_000)


def p(team: str, salary: int | None, pid: int | None = None, **kw) -> Player:
    pid = pid if pid is not None else next(_ids)
    return Player(player_id=pid, name=kw.pop("name", f"P{pid}"), team=team, salary=salary, **kw)


def team(
    abbr: str, payroll: int, *players: Player, standard: int = 14, two_way: int = 0
) -> TeamState:
    explicit = [x for x in players if not x.is_two_way]
    fillers = max(0, standard - len(explicit))
    remaining = payroll - sum(x.salary or 0 for x in explicit)
    roster = list(players)
    if fillers:
        each = remaining // fillers
        roster += [p(abbr, each, name=f"{abbr} filler {i}") for i in range(fillers - 1)]
        roster.append(p(abbr, remaining - each * (fillers - 1), name=f"{abbr} filler last"))
        dead = 0
    else:
        dead = remaining
    roster += [
        p(abbr, 600_000, is_two_way=True)
        for _ in range(two_way - sum(x.is_two_way for x in players))
    ]
    return TeamState(team=abbr, players=roster, dead_money=dead)


def own_picks(abbrs: list[str]) -> dict[str, PickAsset]:
    out = {}
    for a in abbrs:
        for y in range(SEASON.draft.first_tradable_year, SEASON.draft.last_tradable_year + 1):
            for r in (1, 2):
                aid = f"{y}-{r}-{a}"
                out[aid] = PickAsset(asset_id=aid, year=y, round=r, owner=a, original=a, kind="own")
    return out


def league(*teams: TeamState, picks: dict[str, PickAsset] | None = None) -> LeagueState:
    abbrs = [t.team for t in teams]
    return LeagueState(
        season=SEASON,
        teams={t.team: t for t in teams},
        picks=picks if picks is not None else own_picks(abbrs),
    )


def leg(frm: str, to: str, players=(), picks=(), cash: int = 0) -> TradeLeg:
    ids = [x.player_id if isinstance(x, Player) else x for x in players]
    return TradeLeg(from_team=frm, to_team=to, players=ids, picks=list(picks), cash=cash)


def trade(*legs: TradeLeg, day: date = IN_SEASON) -> Trade:
    return Trade(legs=list(legs), trade_date=day)


def check(lg: LeagueState, *legs: TradeLeg, day: date = IN_SEASON) -> TradeVerdict:
    return validate_trade(trade(*legs, day=day), lg)


def codes(verdict: TradeVerdict) -> list[str]:
    return sorted(v.code for v in verdict.violations)


def warning_codes(verdict: TradeVerdict) -> list[str]:
    return sorted(v.code for v in verdict.warnings)


@pytest.fixture
def season():
    return SEASON
