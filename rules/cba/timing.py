from __future__ import annotations

from rules.context import TradeContext
from rules.models import RuleViolation


def check(ctx: TradeContext) -> list[RuleViolation]:
    cal = ctx.season.calendar
    day = ctx.trade.trade_date
    if not cal.league_year_start <= day <= cal.league_year_end:
        return [
            RuleViolation(
                code="OUTSIDE_LEAGUE_YEAR",
                message=f"{day} is outside the {ctx.season.season} league year ({cal.league_year_start} to {cal.league_year_end}); load that season's rules instead.",
            )
        ]
    if day > cal.trade_deadline:
        return [
            RuleViolation(
                code="TRADE_DEADLINE_PASSED",
                message=f"The {ctx.season.season} trade deadline was {cal.trade_deadline}; trades reopen after the Finals.",
            )
        ]
    return []
