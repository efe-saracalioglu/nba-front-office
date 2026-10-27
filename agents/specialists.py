from __future__ import annotations

import json

from agents import cap_analyst
from agents.deps import Deps, market, prompt
from agents.schemas import Answer, Critiques, Route, ScoutReport, TeamGoal


def route(deps: Deps, request: str) -> Route:
    return deps.llm.structured("router", prompt("router"), request, Route)


def plan_goal(deps: Deps, request: str, team: str) -> TeamGoal:
    sheet = deps.tools.call("get_team_cap_sheet", team=team)
    summary = {
        "team": team, "payroll": sheet["payroll"], "status": sheet["status"], "room_to": sheet["room_to"],
        "first_round_picks_by_year": sheet["first_round_picks_by_year"],
        "roster": [{"name": r["name"], "salary": r["salary"], "projected_ws": r["projected_ws"]} for r in sheet["roster"] if not r["two_way"]],
    }  # fmt: skip
    user = f"Owner's request: {request}\n\nTeam cap sheet:\n{json.dumps(summary)}"
    goal = deps.llm.structured("gm", prompt("gm_goal"), user, TeamGoal)
    goal.team = team
    return goal


def value_candidates(deps: Deps, candidates: list[dict]) -> dict[str, dict]:
    out = {}
    for c in candidates[: market()["candidates_to_value"]]:
        out[c["player_name"]] = deps.tools.call(
            "predict_player_value", player=c["player_name"], team=c["team"]
        )
    return out


def scout(deps: Deps, players: list[str]) -> dict[str, dict]:
    reports = {}
    for name in players[: market()["candidates_to_scout"]]:
        news = deps.tools.call("get_player_news", player=name, limit=3)
        source = json.dumps({"injury": news.get("injury"), "articles": news.get("articles", [])})
        user = f"Player: {name}\n<untrusted>\n{source}\n</untrusted>"
        report = deps.llm.structured("scout", prompt("scout"), user, ScoutReport)
        reports[name] = report.model_dump() | {"player": name}
    return reports


def payroll_lines(deps: Deps, team: str) -> dict:
    s = deps.tools.call("get_team_cap_sheet", team=team)
    payroll = s["payroll"]
    return {"salary_cap": payroll + s["room_to"]["salary_cap"], "luxury_tax": payroll + s["room_to"]["luxury_tax"],
            "first_apron": payroll + s["room_to"]["first_apron"], "second_apron": payroll + s["room_to"]["second_apron"]}  # fmt: skip


def critique(
    deps: Deps, goal: dict, proposals: list[dict], valuations: dict, scouting: dict
) -> list[dict]:
    if not proposals:
        return []
    lines = payroll_lines(deps, goal["team"])
    brief = [
        {k: p[k] for k in ("id", "target", "from_team", "send_players", "send_picks", "receive", "value")}
        | {"payroll_before_after": {t["team"]: [t["payroll_before"], t["payroll_after"]] for t in p["validation"]["teams"]},
           "status_after": {t["team"]: t["status_after"] for t in p["validation"]["teams"]},
           "hard_caps_triggered": {t["team"]: t["hard_cap"] for t in p["validation"]["teams"]},
           "rules_engine": "valid",
           "warnings": p["validation"]["warnings"],
           "scouting": scouting.get(p["target"]),
           "projection_interval": (valuations.get(p["target"]) or {}).get("projection")}
        for p in proposals
    ]  # fmt: skip
    facts = (
        f"League payroll lines (dollars): {json.dumps(lines)}. "
        f"The brief's line is '{goal.get('stay_below', 'none')}'; every proposal below already ends under it."
    )
    user = f"{facts}\n\nBrief: {json.dumps(goal)}\n\nProposals:\n{json.dumps(brief)}"
    return [
        c.model_dump()
        for c in deps.llm.structured(
            "devils_advocate", prompt("devils_advocate"), user, Critiques
        ).critiques
    ]


def _m(v: float | None) -> str:
    return "unknown" if v is None else f"${v / 1e6:.1f}M"


def _hard_cap_note(line: str | None) -> str:
    if not line:
        return "no hard cap"
    name = line.replace("_", " ")
    return f"the trade is legal and does not exceed the {name}; afterwards our payroll may not go above the {name} for the rest of the season"


def _line_note(line: tuple[str, int] | None, payroll_after: int) -> str:
    if not line:
        return "the brief sets no payroll line"
    name, value = line[0].replace("_", " "), line[1]
    side = "below it, as the brief requires" if payroll_after < value else "NOT below it"
    return f"brief: stay below the {name} ({_m(value)}); payroll after this trade is {_m(payroll_after)}, {side}"


def fact_sheet(
    p: dict, team: str, critique_by_id: dict, line: tuple[str, int] | None = None
) -> dict:
    ours = next(t for t in p["validation"]["teams"] if t["team"] == team)
    c = critique_by_id.get(p["id"], {})
    return {
        "id": p["id"],
        "we_receive": f"{p['receive']['name']} from {p['from_team']} (salary {_m(p['receive']['salary'])}, projected {p['receive']['projected_ws']:.1f} WS)",
        "we_send": [f"{x['name']} (salary {_m(x['salary'])}, projected {x['projected_ws']:.1f} WS)" for x in p["send_players"]]
                   + [f"{x['round']}st-round pick {x['year']} ({x['asset_id']})" if x["round"] == 1 else f"2nd-round pick {x['year']} ({x['asset_id']})" for x in p["send_picks"]],
        "win_shares_change_for_us": f"{p['value']['ws_change_for_us']:+.1f}",
        "contract_value_change_for_us": _m(p["value"]["our_value_change"]),
        "contract_value_change_for_them": _m(p["value"]["counterparty_value_change"]),
        "our_payroll": f"{_m(ours['payroll_before'])} -> {_m(ours['payroll_after'])} ({ours['status_after'].replace('_', ' ')})",
        "payroll_line": _line_note(line, ours["payroll_after"]),
        "hard_cap": _hard_cap_note(ours["hard_cap"]),
        "roster_after": f"{ours['standard_roster_after']} standard contracts",
        "devils_advocate": {"verdict": c.get("verdict"), "concerns": [x["issue"] for x in c.get("concerns", [])]},
    }  # fmt: skip


def write_memo(deps: Deps, state: dict) -> str:
    team = state.get("team")
    approved_ids = (state.get("approval") or {}).get("approved", [])
    by_id = {c["proposal_id"]: c for c in state.get("critiques", [])}
    proposals = state.get("proposals", [])
    goal = state.get("goal") or {}
    line = None
    if goal.get("stay_below", "none") != "none" and proposals:
        sheet = deps.tools.call("get_team_cap_sheet", team=team)
        key = cap_analyst.LINE_KEYS[goal["stay_below"]]
        line = (goal["stay_below"], sheet["payroll"] + sheet["room_to"][key])
    data = {
        "owner_request": state["request"],
        "brief": state.get("goal"),
        "trade_deadline": deps.tools.read("frontoffice://cba-rules").split("Trade deadline: ")[-1].split(".")[0],
        "approved_proposals": [fact_sheet(p, team, by_id, line) for p in proposals if p["id"] in approved_ids],
        "rejected_or_dropped": [fact_sheet(p, team, by_id, line) for p in proposals if p["id"] not in approved_ids],
        "owner_notes": (state.get("approval") or {}).get("notes"),
        "other_targets_and_why_no_deal": state.get("target_outcomes", {}),
        "scouting": {k: v["summary"] for k, v in state.get("scouting", {}).items()},
    }  # fmt: skip
    return deps.llm.text("memo", prompt("memo"), json.dumps(data, default=str))


def answer_player(deps: Deps, request: str, player: str) -> str:
    value = deps.tools.call("predict_player_value", player=player)
    news = deps.tools.call("get_player_news", player=player, limit=3)
    data = {"question": request, "valuation": value,
            "injury": news.get("injury"), "headlines": [a["title"] for a in news.get("articles", [])]}  # fmt: skip
    return deps.llm.structured("gm", prompt("answer"), json.dumps(data, default=str), Answer).answer
