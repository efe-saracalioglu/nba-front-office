from __future__ import annotations

from rules.context import TeamFlow, TradeContext
from rules.models import RuleViolation


def hard_cap(flow: TeamFlow, ctx: TradeContext) -> str | None:
    if flow.aggregates or flow.cash_sent > 0:
        return "second_apron"
    if flow.in_salary > flow.out_salary and flow.payroll_after > ctx.season.salary_cap:
        return "first_apron"
    return None


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    second = ctx.season.second_apron
    for flow in ctx.flows.values():
        if flow.payroll_after <= second:
            continue
        if flow.aggregates:
            out.append(
                RuleViolation(
                    code="SECOND_APRON_AGGREGATION", team=flow.team,
                    message=f"{flow.team} would finish above the second apron (${flow.payroll_after:,}) and cannot combine the salaries of {flow.salaried_out_count} players in one trade.",
                    details={"payroll_after": flow.payroll_after, "second_apron": second},
                )
            )  # fmt: skip
        if flow.cash_sent > 0:
            out.append(
                RuleViolation(
                    code="SECOND_APRON_CASH", team=flow.team,
                    message=f"{flow.team} would finish above the second apron (${flow.payroll_after:,}) and cannot send cash in a trade.",
                    details={"payroll_after": flow.payroll_after, "cash_sent": flow.cash_sent},
                )
            )  # fmt: skip
    return out
