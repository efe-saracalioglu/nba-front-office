from __future__ import annotations

import itertools
import json
from datetime import date

import duckdb
import pandas as pd

from data.crosswalk import normalize_name
from rules.context import cap_status
from rules.engine import validate_trade
from rules.models import Player, Trade, TradeLeg
from rules.state import LeagueState


class ToolInputError(ValueError):
    pass


def _team(lg: LeagueState, team: str) -> str:
    abbr = team.strip().upper()
    if abbr not in lg.teams:
        raise ToolInputError(
            f"Unknown team {team!r}. Use an NBA abbreviation such as BOS, LAL or NYK."
        )
    return abbr


def resolve_player(lg: LeagueState, name: str, team: str | None = None) -> Player:
    team = _team(lg, team) if team else None
    exact = lg.find_player(name, team)
    if exact:
        return exact
    needle = normalize_name(name)
    pool = [
        p
        for p in (pl for t in lg.teams.values() for pl in t.players)
        if team is None or p.team == team
    ]
    partial = [p for p in pool if needle and needle in normalize_name(p.name)]
    if len(partial) == 1:
        return partial[0]
    where = f" on {team}" if team else ""
    if not partial:
        raise ToolInputError(f"No rostered player matches {name!r}{where}. Try search_players.")
    options = ", ".join(f"{p.name} ({p.team})" for p in partial[:6])
    raise ToolInputError(f"{name!r}{where} is ambiguous: {options}. Pass the full name or a team.")


def _projection(con: duckdb.DuckDBPyConnection, player_id: int) -> dict | None:
    df = con.execute(
        "SELECT projected_ws, ws_p10, ws_p90, market_value, surplus_value, top_factors "
        "FROM player_projections WHERE player_id = ?",
        [player_id],
    ).df()
    if df.empty:
        return None
    rec = df.iloc[0].to_dict()
    rec["top_factors"] = json.loads(rec["top_factors"])
    clean = {k: (None if not isinstance(v, list) and pd.isna(v) else v) for k, v in rec.items()}
    return {k: (round(float(v), 2) if isinstance(v, float) else v) for k, v in clean.items()}


def search_players(
    lg: LeagueState, query: str, team: str | None = None, limit: int = 10
) -> list[dict]:
    team = _team(lg, team) if team else None
    needle = normalize_name(query)
    out = []
    for t in lg.teams.values():
        if team and t.team != team:
            continue
        for p in t.players:
            name = normalize_name(p.name)
            if not needle or needle in name:
                out.append({"player_id": p.player_id, "name": p.name, "team": p.team, "salary": p.salary,
                            "two_way": p.is_two_way, "exact": name == needle})  # fmt: skip
    out.sort(key=lambda r: (not r["exact"], -(r["salary"] or 0)))
    return out[:limit]


def team_cap_sheet(lg: LeagueState, con: duckdb.DuckDBPyConnection, team: str) -> dict:
    abbr = _team(lg, team)
    state, s = lg.teams[abbr], lg.season
    years = (
        con.execute(
            """SELECT c.player_id, count(*) AS years, max(c.season) AS through,
                  max(CASE WHEN c.season = ? THEN c.option_type END) AS option_now
           FROM contracts c JOIN teams t USING (team_id) WHERE t.abbreviation = ? GROUP BY 1""",
            [s.season, abbr],
        )
        .df()
        .set_index("player_id")
    )
    proj = (
        con.execute("SELECT player_id, projected_ws, surplus_value FROM player_projections")
        .df()
        .set_index("player_id")
    )
    injuries = (
        con.execute(
            "SELECT player_id, status FROM injuries QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY report_date DESC) = 1"
        )
        .df()
        .set_index("player_id")
    )
    roster = []
    for p in sorted(state.players, key=lambda x: -(x.salary or 0)):
        y = years.loc[p.player_id] if p.player_id in years.index else None
        pr = proj.loc[p.player_id] if p.player_id in proj.index else None
        roster.append({
            "name": p.name, "salary": p.salary, "two_way": p.is_two_way,
            "contract_through": y["through"] if y is not None else None,
            "option_this_season": y["option_now"] if y is not None and y["option_now"] != "none" else None,
            "signed_on": str(p.signed_on) if p.signed_on else None,
            "projected_ws": round(float(pr["projected_ws"]), 1) if pr is not None else None,
            "surplus_value": int(pr["surplus_value"]) if pr is not None and not pd.isna(pr["surplus_value"]) else None,
            "injury": injuries.loc[p.player_id, "status"] if p.player_id in injuries.index else None,
        })  # fmt: skip
    payroll = state.payroll
    return {
        "team": abbr,
        "season": s.season,
        "payroll": payroll,
        "status": cap_status(payroll, s).value,
        "room_to": {
            "salary_cap": s.salary_cap - payroll, "luxury_tax": s.luxury_tax - payroll,
            "first_apron": s.first_apron - payroll, "second_apron": s.second_apron - payroll,
        },
        "dead_money": state.dead_money,
        "standard_contracts": state.standard_roster,
        "two_way_contracts": state.two_way_roster,
        "first_round_picks_by_year": lg.first_round_holdings(abbr),
        "roster": roster,
    }  # fmt: skip


def _legs(lg: LeagueState, legs: list[dict]) -> list[TradeLeg]:
    out = []
    for i, leg in enumerate(legs, 1):
        try:
            frm, to = _team(lg, leg["from_team"]), _team(lg, leg["to_team"])
        except KeyError as e:
            raise ToolInputError(f"Leg {i} needs from_team and to_team.") from e
        players = [resolve_player(lg, n, frm).player_id for n in leg.get("players", [])]
        out.append(
            TradeLeg(
                from_team=frm,
                to_team=to,
                players=players,
                picks=list(leg.get("picks", [])),
                cash=int(leg.get("cash", 0)),
            )
        )
    return out


def check_trade(lg: LeagueState, legs: list[dict], trade_date: str | None = None) -> dict:
    day = date.fromisoformat(trade_date) if trade_date else date.today()
    verdict = validate_trade(Trade(legs=_legs(lg, legs), trade_date=day), lg)
    return json.loads(verdict.model_dump_json())


def salary_matches(lg: LeagueState, team: str, target: str, max_players: int = 3, limit: int = 8,
                   trade_date: str | None = None) -> dict:  # fmt: skip
    abbr = _team(lg, team)
    goal = resolve_player(lg, target)
    if goal.team == abbr:
        raise ToolInputError(f"{goal.name} already plays for {abbr}.")
    day = date.fromisoformat(trade_date) if trade_date else date.today()
    pool = [p for p in lg.teams[abbr].players if not p.is_two_way and p.salary]
    found = []
    for k in range(1, max_players + 1):
        for combo in itertools.combinations(pool, k):
            out_salary = sum(p.salary for p in combo)
            if out_salary > (goal.salary or 0) * 1.6 + 5_000_000:
                continue
            trade = Trade(trade_date=day, legs=[
                TradeLeg(from_team=abbr, to_team=goal.team, players=[p.player_id for p in combo]),
                TradeLeg(from_team=goal.team, to_team=abbr, players=[goal.player_id]),
            ])  # fmt: skip
            v = validate_trade(trade, lg)
            if v.valid:
                found.append({
                    "send": [{"name": p.name, "salary": p.salary} for p in combo],
                    "outgoing_salary": out_salary,
                    "warnings": [w.message for w in v.warnings],
                })  # fmt: skip
        if len(found) >= limit:
            break
    found.sort(key=lambda f: (len(f["send"]), abs(f["outgoing_salary"] - (goal.salary or 0))))
    return {
        "target": {"name": goal.name, "team": goal.team, "salary": goal.salary},
        "acquiring_team": abbr,
        "packages": found[:limit],
        "note": "Each package passed every rule for both teams on its own, without picks or cash.",
    }


def player_value(
    lg: LeagueState, con: duckdb.DuckDBPyConnection, player: str, team: str | None = None
) -> dict:
    p = resolve_player(lg, player, team)
    proj = _projection(con, p.player_id)
    return {
        "name": p.name, "team": p.team, "salary": p.salary,
        "projection": proj,
        "explanation": (
            "projected_ws is the model's median next-season Win Shares per 82 games; ws_p10..ws_p90 is an "
            "80% interval; surplus_value = market_value - salary in dollars."
            if proj else "No projection: the player logged fewer than 250 NBA minutes last season."
        ),
    }  # fmt: skip


def draft_assets(lg: LeagueState, team: str) -> dict:
    abbr = _team(lg, team)
    owned, traded_away, encumbered = [], [], []
    for a in sorted(lg.picks.values(), key=lambda x: (x.year, x.round, x.asset_id)):
        info = {"asset_id": a.asset_id, "year": a.year, "round": a.round, "kind": a.kind,
                "original_team": a.original, "description": a.description, "protection": a.protection}  # fmt: skip
        if a.owner == abbr:
            owned.append(info)
        elif a.original == abbr and a.counts_as_pick:
            traded_away.append(info | {"now_owned_by": a.owner})
        elif a.kind == "swap_right" and abbr in (a.description or "") + (a.original or ""):
            encumbered.append(info | {"held_by": a.owner})
    return {"team": abbr, "owned": owned, "own_picks_traded_away": traded_away,
            "swap_rights_held_by_others": encumbered,
            "first_round_picks_by_year": lg.first_round_holdings(abbr)}  # fmt: skip
