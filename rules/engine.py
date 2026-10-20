from __future__ import annotations

from collections.abc import Callable

from rules.cba import aprons, cash, eligibility, picks, roster, salary_matching, timing
from rules.context import TeamFlow, TradeContext, cap_status
from rules.models import RuleViolation, TeamTradeSummary, Trade, TradeVerdict
from rules.state import LeagueState

RULES: list[Callable[[TradeContext], list[RuleViolation]]] = [
    timing.check,
    salary_matching.check,
    aprons.check,
    roster.check,
    eligibility.check,
    picks.check,
    cash.check,
]


def _error(code: str, team: str, message: str, **details) -> RuleViolation:
    return RuleViolation(code=code, team=team, message=message, details=details)


def _structure(
    trade: Trade, league: LeagueState
) -> tuple[dict[str, TeamFlow], dict[str, str], list[RuleViolation]]:
    errors: list[RuleViolation] = []
    flows: dict[str, TeamFlow] = {}
    for team in trade.teams:
        if team not in league.teams:
            errors.append(_error("UNKNOWN_TEAM", team, f"{team} is not an NBA team abbreviation."))
        else:
            flows[team] = TeamFlow(team=team, state=league.teams[team])
    if errors:
        return flows, {}, errors

    seen_players: set[int] = set()
    seen_picks: set[str] = set()
    owners_after: dict[str, str] = {}
    for leg in trade.legs:
        giver, taker, frm = flows[leg.from_team], flows[leg.to_team], leg.from_team
        for pid in leg.players:
            player = league.player(pid)
            if player is None or player.team != frm:
                name = player.name if player else pid
                where = f"is on {player.team}" if player else "is not on any roster"
                msg = f"Player {name} {where}, not {frm}."
                errors.append(_error("PLAYER_NOT_ON_TEAM", frm, msg, player_id=pid))
                continue
            if pid in seen_players:
                msg = f"{player.name} appears in more than one leg."
                errors.append(_error("DUPLICATE_ASSET", frm, msg, player_id=pid))
                continue
            if player.salary is None and not player.is_two_way:
                msg = f"{player.name} has no known {league.season.season} salary, so the trade cannot be checked."
                errors.append(_error("SALARY_UNKNOWN", frm, msg, player_id=pid))
            seen_players.add(pid)
            giver.out_players.append(player)
            taker.in_players.append(player)
        for aid in leg.picks:
            pick = league.picks.get(aid)
            if pick is None or pick.owner != frm:
                where = f"belongs to {pick.owner}" if pick else "does not exist"
                errors.append(
                    _error("PICK_NOT_OWNED", frm, f"Pick {aid} {where}, not {frm}.", asset_id=aid)
                )
                continue
            if aid in seen_picks:
                msg = f"Pick {aid} appears in more than one leg."
                errors.append(_error("DUPLICATE_ASSET", frm, msg, asset_id=aid))
                continue
            seen_picks.add(aid)
            owners_after[aid] = leg.to_team
            giver.out_picks.append(pick)
            taker.in_picks.append(pick)
        giver.cash_sent += leg.cash
        taker.cash_received += leg.cash
    return flows, owners_after, errors


def _summary(flow: TeamFlow, ctx: TradeContext) -> TeamTradeSummary:
    s = ctx.season
    tpe = (
        flow.out_salary - flow.in_salary
        if flow.payroll_after > s.salary_cap and flow.out_salary > flow.in_salary
        else 0
    )
    return TeamTradeSummary(
        team=flow.team,
        payroll_before=flow.payroll_before,
        payroll_after=flow.payroll_after,
        status_before=cap_status(flow.payroll_before, s),
        status_after=cap_status(flow.payroll_after, s),
        outgoing_salary=flow.out_salary,
        incoming_salary=flow.in_salary,
        max_incoming_salary=salary_matching.max_incoming_salary(flow, s),
        traded_player_exception=tpe,
        standard_roster_before=flow.state.standard_roster,
        standard_roster_after=flow.standard_after,
        two_way_after=flow.two_way_after,
        hard_cap=aprons.hard_cap(flow, ctx),
    )


def validate_trade(trade: Trade, league: LeagueState) -> TradeVerdict:
    flows, owners_after, structural = _structure(trade, league)
    if any(v.code == "UNKNOWN_TEAM" for v in structural):
        return TradeVerdict(valid=False, violations=structural, warnings=[], teams=[])
    ctx = TradeContext(trade=trade, league=league, flows=flows, pick_owners_after=owners_after)
    found = list(structural)
    for rule in RULES:
        found.extend(rule(ctx))
    errors = [v for v in found if v.severity == "error"]
    warnings = [v for v in found if v.severity == "warning"]
    return TradeVerdict(
        valid=not errors,
        violations=errors,
        warnings=warnings,
        teams=[_summary(f, ctx) for f in flows.values()],
    )
