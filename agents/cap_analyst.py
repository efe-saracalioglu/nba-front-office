from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from agents.deps import Deps, market
from agents.toolbox import ToolCallError
from data.crosswalk import normalize_name

LINE_KEYS = {
    "luxury_tax": "luxury_tax",
    "first_apron": "first_apron",
    "second_apron": "second_apron",
}


@dataclass
class Valuer:
    deps: Deps
    cache: dict[str, dict] = field(default_factory=dict)
    sheets: dict[str, dict] = field(default_factory=dict)

    def player(self, name: str, team: str | None = None) -> dict:
        key = f"{name}|{team}"
        if key not in self.cache:
            self.cache[key] = self.deps.tools.call("predict_player_value", player=name, team=team)
        return self.cache[key]

    def contract_years(self, name: str, team: str) -> int:
        if team not in self.sheets:
            self.sheets[team] = self.deps.tools.call("get_team_cap_sheet", team=team)
        sheet = self.sheets[team]
        key = normalize_name(name)
        row = next((r for r in sheet["roster"] if normalize_name(r["name"]) == key), None)
        start = int(sheet["season"][:4])
        through = (
            row["contract_through"] if row and row.get("contract_through") else sheet["season"]
        )
        return max(1, min(market()["max_contract_years"], int(through[:4]) - start + 1))

    def season_surplus(self, name: str, team: str | None = None) -> float:
        v = self.player(name, team)
        proj = v.get("projection")
        if proj and proj.get("surplus_value") is not None:
            return float(proj["surplus_value"])
        min_salary = 1_357_763
        return float(min_salary - (v.get("salary") or min_salary))

    def surplus(self, name: str, team: str) -> float:
        cfg = market()
        star = cfg["star_premium_per_ws"] * max(0.0, self.ws(name, team) - cfg["star_threshold_ws"])
        return (self.season_surplus(name, team) + star) * self.contract_years(name, team)

    def ws(self, name: str, team: str | None = None) -> float:
        proj = self.player(name, team).get("projection")
        return float(proj["projected_ws"]) if proj else 0.0


def pick_value(pick: dict) -> float:
    m = market()["pick_value"]
    if pick["kind"] == "swap_right":
        return m["swap_right"]
    return m["first_round"] if pick["round"] == 1 else m["second_round"]


def tradable_picks(assets: dict, protected: list[str]) -> list[dict]:
    blocked_years = {p for p in protected if p.isdigit()}
    blocked_ids = set(protected) - blocked_years
    out = [
        a
        for a in assets["owned"]
        if a["kind"] in ("own", "acquired")
        and str(a["year"]) not in blocked_years
        and a["asset_id"] not in blocked_ids
    ]
    return sorted(out, key=lambda a: (a["round"] == 1, -a["year"]))


def _rank(p: dict) -> tuple[float, float]:
    return (p["value"]["ws_change_for_us"], p["value"]["our_value_change"])


def required_first_round_picks(valuer: Valuer, target: dict, send: list[dict], team: str) -> int:
    cfg = market()
    loss = valuer.ws(target["player_name"], target["team"]) - sum(
        valuer.ws(p["name"], team) for p in send
    )
    age = target.get("age")
    if age is not None and age <= cfg["young_player_age"]:
        loss *= cfg["young_ws_loss_multiplier"]
    return max(
        0, math.ceil((loss - cfg["counterparty_max_ws_loss"]) / cfg["ws_per_first_round_pick"])
    )


def _payroll_line(cap_sheet: dict, line: str) -> int | None:
    if line == "none":
        return None
    return cap_sheet["payroll"] + cap_sheet["room_to"][LINE_KEYS[line]]


def build_package(
    deps: Deps,
    valuer: Valuer,
    goal: dict,
    target: dict,
    send: list[dict],
    picks_pool: list[dict],
    trade_date: str,
    line_value: int | None,
    extra_picks: int = 0,
) -> dict | str:
    cfg = market()
    team, other = goal["team"], target["team"]
    target_surplus = valuer.surplus(target["player_name"], other)
    players_value = sum(valuer.surplus(p["name"], team) for p in send)
    pool = list(picks_pool)
    firsts = required_first_round_picks(valuer, target, send, team)
    if firsts > cfg["max_sweetener_picks"]:
        return f"{other} would not give up that much talent for picks we can offer"
    chosen = [p for p in pool if p["round"] == 1][:firsts]
    if len(chosen) < firsts:
        if not goal.get("trade_first_round_picks", True):
            return f"{other} would want first-round picks for the talent it loses, and the brief rules them out"
        return (
            f"{other} would want more first-round picks for the talent it loses than we can trade"
        )
    pool = [p for p in pool if p not in chosen]
    gap = players_value + sum(pick_value(p) for p in chosen) - target_surplus
    while (
        (gap < -cfg["counterparty_tolerance"] or len(chosen) < extra_picks)
        and pool
        and len(chosen) < cfg["max_sweetener_picks"] + extra_picks
    ):
        chosen.append(pool.pop(0))
        gap = players_value + sum(pick_value(p) for p in chosen) - target_surplus
    if gap < -cfg["counterparty_tolerance"]:
        return f"{other} would lose too much contract value, even after adding our tradable picks"
    for _ in range(4):
        legs = [
            {
                "from_team": team,
                "to_team": other,
                "players": [p["name"] for p in send],
                "picks": [p["asset_id"] for p in chosen],
            },
            {"from_team": other, "to_team": team, "players": [target["player_name"]]},
        ]
        try:
            verdict = deps.tools.call("validate_trade", legs=legs, trade_date=trade_date)
        except ToolCallError as e:
            return f"could not be checked: {e}"
        codes = {v["code"] for v in verdict["violations"]}
        if verdict["valid"]:
            break
        if codes == {"STEPIEN"} and pool:
            bad = next((p for p in chosen if p["round"] == 1), None)
            replacement = next(
                (p for p in pool if p["round"] == 1 and bad and p["year"] != bad["year"]), None
            )
            if bad is None or replacement is None:
                return "the picks needed to balance it would break the Stepien rule"
            chosen.remove(bad)
            pool.remove(replacement)
            chosen.append(replacement)
            continue
        return "rules engine rejected the sweetened package: " + ", ".join(sorted(codes))
    else:
        return "the picks needed to balance it would break the Stepien rule"
    ours = next(t for t in verdict["teams"] if t["team"] == team)
    if line_value is not None and ours["payroll_after"] >= line_value:
        return f"would push our payroll above the {goal['stay_below'].replace('_', ' ')}"
    picks_value = sum(pick_value(p) for p in chosen)
    return {
        "target": target["player_name"],
        "from_team": other,
        "send_players": [
            {
                "name": p["name"],
                "salary": p["salary"],
                "projected_ws": round(valuer.ws(p["name"], team), 2),
                "surplus_value": round(valuer.surplus(p["name"], team)),
            }
            for p in send
        ],
        "send_picks": [
            {
                "asset_id": p["asset_id"],
                "year": p["year"],
                "round": p["round"],
                "protection": p.get("protection"),
            }
            for p in chosen
        ],
        "receive": {
            "name": target["player_name"],
            "salary": target["salary"],
            "projected_ws": round(valuer.ws(target["player_name"], other), 2),
            "surplus_value": round(target_surplus),
        },
        "value": {
            "our_value_change": round(target_surplus - players_value - picks_value),
            "counterparty_value_change": round(players_value + picks_value - target_surplus),
            "ws_change_for_us": round(
                valuer.ws(target["player_name"], other)
                - sum(valuer.ws(p["name"], team) for p in send),
                2,
            ),
            "picks_value_assumed": round(picks_value),
            "first_round_picks_for_talent": firsts,
        },
        "validation": {
            "valid": True,
            "teams": verdict["teams"],
            "warnings": [w["message"] for w in verdict["warnings"]],
        },
        "legs": legs,
        "trade_date": trade_date,
    }


def propose(
    deps: Deps,
    goal: dict,
    candidates: list[dict],
    scouting: dict,
    trade_date: str,
    extra_picks: dict[str, int] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    cfg = market()
    team = goal["team"]
    valuer = Valuer(deps)
    cap_sheet = deps.tools.call("get_team_cap_sheet", team=team)
    assets = deps.tools.call("get_draft_assets", team=team)
    picks_pool = tradable_picks(assets, goal.get("protected_picks", []))
    if not goal.get("trade_first_round_picks", True):
        picks_pool = [p for p in picks_pool if p["round"] != 1]
    line_value = _payroll_line(cap_sheet, goal.get("stay_below", "none"))
    untouchable = {u.lower() for u in goal.get("untouchable_players", [])}
    extra_picks = extra_picks or {}
    proposals, outcomes = [], {}
    for target in candidates:
        name = target["player_name"]
        report = scouting.get(name, {})
        if report.get("availability") == "out" and report.get("risk") == "high":
            outcomes[name] = "skipped: out with a high-risk injury"
            continue
        try:
            matches = deps.tools.call(
                "find_salary_matches",
                team=team,
                target_player=name,
                max_players=3,
                limit=20,
                trade_date=trade_date,
            )
        except ToolCallError as e:
            outcomes[name] = f"could not be checked: {e}"
            continue
        best, reasons = None, Counter()
        packages = [
            pkg
            for pkg in matches["packages"]
            if not any(p["name"].lower() in untouchable for p in pkg["send"])
        ]
        if not packages:
            suffix = " without untouchable players" if untouchable and matches["packages"] else ""
            outcomes[name] = f"no salary-matching package of up to three {team} players{suffix}"
            continue
        for pkg in packages:
            built = build_package(
                deps,
                valuer,
                goal,
                target,
                pkg["send"],
                picks_pool,
                trade_date,
                line_value,
                extra_picks.get(name, 0),
            )
            if isinstance(built, str):
                reasons[built] += 1
                continue
            if built["value"]["ws_change_for_us"] <= 0:
                reasons["no legal package makes us better in projected Win Shares"] += 1
                continue
            if best is None or _rank(built) > _rank(best):
                best = built
        if best:
            proposals.append(best)
            outcomes[name] = "proposal built"
        else:
            outcomes[name] = reasons.most_common(1)[0][0]
    proposals.sort(key=_rank, reverse=True)
    kept = proposals[: cfg["proposals_to_keep"]]
    for i, p in enumerate(kept, 1):
        p["id"] = f"P{i}"
    for p in proposals[cfg["proposals_to_keep"] :]:
        outcomes[p["target"]] = "legal, but ranked below the proposals kept"
    return kept, outcomes
