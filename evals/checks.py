from __future__ import annotations

from functools import cache

from agents.cap_analyst import Valuer, pick_value
from agents.deps import Deps, market
from agents.toolbox import ToolBox, ToolCallError
from data.crosswalk import normalize_name
from mcp_server.warehouse import connect
from rules.season import load_season

LINES = {"luxury_tax": "luxury_tax", "first_apron": "first_apron", "second_apron": "second_apron"}


@cache
def player_facts() -> dict[str, dict]:
    con = connect()
    rows = con.execute(
        """SELECT p.player_name, p.position, j.age_next, j.projected_ws
           FROM players p LEFT JOIN player_projections j USING (player_id)"""
    ).fetchall()
    con.close()
    return {
        normalize_name(n): {"name": n, "position": pos, "age": age, "projected_ws": ws}
        for n, pos, age, ws in rows
    }


def facts_for(name: str) -> dict:
    return player_facts().get(
        normalize_name(name), {"name": name, "position": None, "age": None, "projected_ws": None}
    )


def _picks_out(legs: list[dict], team: str) -> list[str]:
    return [p for leg in legs if leg.get("from_team") == team for p in leg.get("picks", [])]


def _players(legs: list[dict], team: str, direction: str) -> list[str]:
    key = "from_team" if direction == "out" else "to_team"
    return [p for leg in legs if leg.get(key) == team for p in leg.get("players", [])]


def check_proposal(
    legs: list[dict], team: str, checks: dict, trade_date: str, tools: ToolBox, valuer: Valuer
) -> dict:
    season = load_season()
    result: dict = {"legal": False, "violations": [], "failed_checks": []}
    try:
        verdict = tools.call("validate_trade", legs=legs, trade_date=trade_date)
    except ToolCallError as e:
        result["violations"] = [f"could not be validated: {e}"]
        result["failed_checks"].append("legal")
        return result
    result["legal"] = verdict["valid"]
    result["violations"] = [v["code"] for v in verdict["violations"]]
    if not verdict["valid"]:
        result["failed_checks"].append("legal")
    ours = next((t for t in verdict["teams"] if t["team"] == team), None)
    incoming, outgoing = _players(legs, team, "in"), _players(legs, team, "out")
    picks_out = _picks_out(legs, team)
    failed = result["failed_checks"]

    if not incoming:
        failed.append("receives_a_player")
    protected = {int(y) for y in checks.get("protected_years", [])}
    if any(int(p[:4]) in protected for p in picks_out):
        failed.append("protected_picks")
    if checks.get("no_first_round_picks") and any(p.split("-")[1] == "1" for p in picks_out):
        failed.append("no_first_round_picks")
    untouchable = {normalize_name(u) for u in checks.get("untouchable", [])}
    if any(normalize_name(p) in untouchable for p in outgoing):
        failed.append("untouchable")
    if ours:
        line = checks.get("stay_below")
        if line and line != "none" and ours["payroll_after"] >= getattr(season, LINES[line]):
            failed.append("stay_below")
        if checks.get("payroll_must_drop") and ours["payroll_after"] >= ours["payroll_before"]:
            failed.append("payroll_must_drop")
        if checks.get("payroll_must_not_rise") and ours["payroll_after"] > ours["payroll_before"]:
            failed.append("payroll_must_not_rise")
    in_facts = [facts_for(p) for p in incoming]
    if checks.get("positions") and not any(f["position"] in checks["positions"] for f in in_facts):
        failed.append("position_fit")
    if checks.get("max_age") and not any(
        f["age"] is not None and f["age"] <= checks["max_age"] for f in in_facts
    ):
        failed.append("max_age")
    if checks.get("min_projected_ws") and not any(
        (f["projected_ws"] or 0) >= checks["min_projected_ws"] for f in in_facts
    ):
        failed.append("min_projected_ws")

    if verdict["valid"]:
        other = next((leg["from_team"] for leg in legs if leg.get("to_team") == team), None)
        try:
            gain = sum(valuer.surplus(p, other) for p in incoming)
            loss = sum(valuer.surplus(p, team) for p in outgoing)
            picks = sum(
                pick_value({"kind": "own", "round": int(p.split("-")[1])}) for p in picks_out
            )
            ws = sum(valuer.ws(p, other) for p in incoming) - sum(
                valuer.ws(p, team) for p in outgoing
            )
            result["value"] = {
                "ws_change_for_us": round(ws, 2),
                "counterparty_value_change": round(loss + picks - gain),
            }
            if ws <= 0:
                failed.append("improves_us")
            if loss + picks - gain < -market()["counterparty_tolerance"]:
                failed.append("counterparty_realism")
        except ToolCallError:
            failed.append("valuation")
    result["incoming"] = in_facts
    result["outgoing"] = outgoing
    result["picks_out"] = picks_out
    result["payroll_before_after"] = (
        [ours["payroll_before"], ours["payroll_after"]] if ours else None
    )
    result["passes_all"] = not failed
    return result


def check_output(
    proposals: list[list[dict]], team: str, checks: dict, trade_date: str
) -> list[dict]:
    deps = Deps()
    valuer = Valuer(deps)
    return [
        check_proposal(legs, team, checks, trade_date, deps.tools, valuer) for legs in proposals
    ]
