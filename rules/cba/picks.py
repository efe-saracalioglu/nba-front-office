from __future__ import annotations

from rules.context import TradeContext
from rules.models import RuleViolation


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    d = ctx.season.draft
    for flow in ctx.flows.values():
        for pick in flow.out_picks:
            if not d.first_tradable_year <= pick.year <= d.last_tradable_year:
                out.append(
                    RuleViolation(
                        code="PICK_OUT_OF_WINDOW", team=flow.team,
                        message=f"{pick.asset_id} is outside the tradable window {d.first_tradable_year}-{d.last_tradable_year}.",
                        details={"asset_id": pick.asset_id},
                    )
                )  # fmt: skip
        firsts_sent = {p.year for p in flow.out_picks if p.round == 1 and p.counts_as_pick}
        if not firsts_sent:
            continue
        holdings = ctx.league.first_round_holdings(flow.team, ctx.pick_owners_after)
        for year in range(d.first_tradable_year, d.last_tradable_year):
            pair = (year, year + 1)
            if holdings[year] == 0 and holdings[year + 1] == 0 and firsts_sent & set(pair):
                out.append(
                    RuleViolation(
                        code="STEPIEN", team=flow.team,
                        message=f"{flow.team} would have no first-round pick in both {year} and {year + 1} (Stepien rule).",
                        details={"years": list(pair)},
                    )
                )  # fmt: skip
                break
    return out
