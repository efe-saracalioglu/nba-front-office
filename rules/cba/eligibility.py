from __future__ import annotations

import calendar
from datetime import date, timedelta

from rules.context import TradeContext
from rules.models import Player, RuleViolation
from rules.season import SeasonConfig


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def tradable_from(player: Player, season: SeasonConfig) -> date | None:
    if player.signed_on is None:
        return None
    s = season.signing
    after_wait = add_months(player.signed_on, s.wait_months)
    if player.signed_on >= s.offseason_start:
        return max(after_wait, s.offseason_trade_date)
    return after_wait


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    day = ctx.trade.trade_date
    wait = timedelta(days=ctx.season.trade.aggregation_wait_days)
    for flow in ctx.flows.values():
        for p in flow.out_players:
            eligible = tradable_from(p, ctx.season)
            if eligible and day < eligible:
                out.append(
                    RuleViolation(
                        code="RECENTLY_SIGNED", team=flow.team,
                        message=f"{p.name} signed on {p.signed_on} and cannot be traded until {eligible}.",
                        details={"player_id": p.player_id, "signed_on": str(p.signed_on), "eligible": str(eligible)},
                    )
                )  # fmt: skip
            acquired = p.acquired_by_trade_on
            if flow.aggregates and acquired and day < acquired + wait:
                out.append(
                    RuleViolation(
                        code="AGGREGATION_TOO_SOON", team=flow.team,
                        message=f"{p.name} was acquired by trade on {acquired} and cannot be combined with other salaries until {acquired + wait}.",
                        details={"player_id": p.player_id, "acquired": str(acquired)},
                    )
                )  # fmt: skip
    return out
