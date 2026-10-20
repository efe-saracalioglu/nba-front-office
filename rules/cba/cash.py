from __future__ import annotations

from rules.context import TradeContext
from rules.models import RuleViolation


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    limit = ctx.season.trade.cash_limit
    for flow in ctx.flows.values():
        for amount, direction in ((flow.cash_sent, "send"), (flow.cash_received, "receive")):
            if amount > limit:
                out.append(
                    RuleViolation(
                        code="CASH_LIMIT", team=flow.team,
                        message=f"{flow.team} would {direction} ${amount:,} in cash; the season limit is ${limit:,}.",
                        details={"amount": amount, "limit": limit, "direction": direction},
                    )
                )  # fmt: skip
    return out
