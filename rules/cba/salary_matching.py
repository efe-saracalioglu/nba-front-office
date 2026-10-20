from __future__ import annotations

from rules.context import TeamFlow, TradeContext
from rules.models import RuleViolation
from rules.season import SeasonConfig


def expanded_matching_limit(outgoing: int, season: SeasonConfig) -> int:
    cushion = season.trade.matching_cushion
    return max(
        min(2 * outgoing + cushion, outgoing + season.trade.matching_bracket),
        int(1.25 * outgoing) + cushion,
    )


def max_incoming_salary(flow: TeamFlow, season: SeasonConfig) -> int:
    out, payroll = flow.out_salary, flow.payroll_before
    room_path = season.salary_cap - payroll + out
    expanded_path = min(expanded_matching_limit(out, season), season.first_apron - payroll + out)
    apron_path = int(out * season.trade.apron_matching_pct)
    return max(room_path, expanded_path, apron_path)


def check(ctx: TradeContext) -> list[RuleViolation]:
    out = []
    for flow in ctx.flows.values():
        if flow.in_salary == 0:
            continue
        limit = max_incoming_salary(flow, ctx.season)
        if flow.in_salary <= limit:
            continue
        if flow.out_salary == 0:
            code, why = (
                "ABSORB_WITHOUT_ROOM",
                "takes in salary without sending any out and has no cap room for it",
            )
        elif flow.payroll_after > ctx.season.first_apron:
            code, why = (
                "SALARY_MATCHING_APRON",
                "would finish above the first apron, so it can take back at most 100% of outgoing salary",
            )
        else:
            code, why = "SALARY_MATCHING", "takes back more salary than the matching rules allow"
        out.append(
            RuleViolation(
                code=code, team=flow.team,
                message=f"{flow.team} {why}: incoming ${flow.in_salary:,} vs allowed ${limit:,} (outgoing ${flow.out_salary:,}).",
                details={"incoming": flow.in_salary, "outgoing": flow.out_salary, "allowed": limit,
                         "payroll_before": flow.payroll_before, "payroll_after": flow.payroll_after},
            )
        )  # fmt: skip
    return out
