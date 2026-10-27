from __future__ import annotations

from rules.context import TradeContext
from rules.models import RuleViolation


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    r = ctx.season.roster
    in_season = ctx.trade.trade_date >= ctx.season.calendar.regular_season_start
    limit = r.max_standard if in_season else r.offseason_max_standard
    for flow in ctx.flows.values():
        after = flow.standard_after
        if after > limit and after > flow.state.standard_roster:
            out.append(
                RuleViolation(
                    code="ROSTER_MAX",
                    team=flow.team,
                    message=f"{flow.team} would carry {after} standard contracts; the limit is {limit}. It must waive or include players first.",
                    details={"after": after, "limit": limit},
                )
            )
        elif in_season and after < r.temporary_min_standard:
            out.append(
                RuleViolation(
                    code="ROSTER_MIN",
                    team=flow.team,
                    message=f"{flow.team} would drop to {after} standard contracts; the floor is {r.temporary_min_standard}.",
                    details={"after": after, "floor": r.temporary_min_standard},
                )
            )
        elif in_season and after < r.min_standard:
            out.append(
                RuleViolation(
                    code="ROSTER_BELOW_MIN",
                    team=flow.team,
                    severity="warning",
                    message=f"{flow.team} would carry {after} standard contracts and must get back to {r.min_standard} within two weeks.",
                    details={"after": after},
                )
            )
        if flow.two_way_after > r.max_two_way:
            out.append(
                RuleViolation(
                    code="TWO_WAY_MAX",
                    team=flow.team,
                    message=f"{flow.team} would carry {flow.two_way_after} two-way players; the limit is {r.max_two_way}.",
                    details={"after": flow.two_way_after},
                )
            )
    return out
