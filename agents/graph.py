from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import cap_analyst, specialists, stats_analyst
from agents.deps import Deps
from agents.state import FrontOfficeState
from agents.tracing import traced_node
from data.config import DATA_DIR

CHECKPOINTS = Path(os.environ.get("FRONT_OFFICE_CHECKPOINTS", DATA_DIR / "checkpoints.sqlite"))
MAX_REVISIONS = 1


def build(deps: Deps, checkpoint_path: Path | None = CHECKPOINTS, human_in_the_loop: bool = True):
    def router(state: FrontOfficeState) -> dict:
        r = specialists.route(deps, state["request"])
        team = state.get("team") or r.team
        out = {"route": r.route, "player": r.player, "team": team.upper() if team else None,
               "trade_date": state.get("trade_date") or date.today().isoformat()}  # fmt: skip
        return out | deps.flush(
            f"router: {r.route}" + (f" for {out['team']}" if out["team"] else "")
        )

    def after_router(state: FrontOfficeState) -> str:
        if state["route"] == "trade_search" and not state.get("team"):
            return "need_team"
        return state["route"]

    def need_team(state: FrontOfficeState) -> dict:
        return {"error": "Which team are you running? Pass --team (e.g. BOS) or name the team in the request.",
                "events": ["stopped: no team"]}  # fmt: skip

    def gm_plan(state: FrontOfficeState) -> dict:
        goal = specialists.plan_goal(deps, state["request"], state["team"])
        return {"goal": goal.model_dump()} | deps.flush(
            f"gm: {goal.need} ({', '.join(goal.positions)})"
        )

    def stats(state: FrontOfficeState) -> dict:
        rows, attempts = stats_analyst.find_candidates(deps, state["goal"])
        tries = sum(1 for a in attempts if a["attempt"] != "fallback")
        return {"candidates": rows, "sql_attempts": attempts} | deps.flush(
            f"stats: {len(rows)} candidates after {tries} SQL attempt(s)"
        )

    def valuation(state: FrontOfficeState) -> dict:
        vals = specialists.value_candidates(deps, state["candidates"])
        return {"valuations": vals} | deps.flush(f"valuation: {len(vals)} players valued")

    def scout(state: FrontOfficeState) -> dict:
        names = [c["player_name"] for c in state["candidates"]]
        reports = specialists.scout(deps, names)
        flagged = [n for n, r in reports.items() if r["suspicious_content"]]
        note = f"scout: {len(reports)} reports" + (
            f", suspicious text in {flagged}" if flagged else ""
        )
        return {"scouting": reports} | deps.flush(note)

    def cap(state: FrontOfficeState) -> dict:
        extra = {}
        for c in state.get("critiques", []):
            if c["verdict"] == "revise" and not c["counterparty_would_accept"]:
                target = next(
                    (
                        p["target"]
                        for p in state.get("proposals", [])
                        if p["id"] == c["proposal_id"]
                    ),
                    None,
                )
                if target:
                    extra[target] = 1
        dropped = {p["target"] for p in state.get("proposals", [])
                   for c in state.get("critiques", []) if c["proposal_id"] == p["id"] and c["verdict"] == "drop"}  # fmt: skip
        candidates = [c for c in state["candidates"] if c["player_name"] not in dropped]
        props, outcomes = cap_analyst.propose(
            deps, state["goal"], candidates, state.get("scouting", {}), state["trade_date"], extra
        )
        for name in dropped:
            outcomes[name] = "dropped by the devil's advocate"
        revision = state.get("revisions", 0) + (1 if state.get("critiques") else 0)
        return {
            "proposals": props,
            "target_outcomes": outcomes,
            "revisions": revision,
        } | deps.flush(
            f"cap: {len(props)} legal proposals" + (f" (revision {revision})" if revision else "")
        )

    def devils_advocate(state: FrontOfficeState) -> dict:
        crit = specialists.critique(
            deps,
            state["goal"],
            state["proposals"],
            state.get("valuations", {}),
            state.get("scouting", {}),
        )
        verdicts = (
            ", ".join(f"{c['proposal_id']}={c['verdict']}" for c in crit) or "nothing to review"
        )
        return {"critiques": crit} | deps.flush(f"devil's advocate: {verdicts}")

    def after_critique(state: FrontOfficeState) -> str:
        needs_work = any(
            c["verdict"] == "drop"
            or (c["verdict"] == "revise" and not c["counterparty_would_accept"])
            for c in state.get("critiques", [])
        )
        return "cap" if needs_work and state.get("revisions", 0) < MAX_REVISIONS else "approval"

    def approval(state: FrontOfficeState) -> dict:
        ids = [p["id"] for p in state.get("proposals", [])]
        if not human_in_the_loop:
            dropped = {
                c["proposal_id"] for c in state.get("critiques", []) if c["verdict"] == "drop"
            }
            kept = [i for i in ids if i not in dropped]
            return {"approval": {"approved": kept, "notes": "auto-approved: proposals the devil's advocate did not drop"},
                    "events": [f"approval: auto {kept or 'none'}"]}  # fmt: skip
        decision = interrupt(
            {"proposals": state.get("proposals", []), "critiques": state.get("critiques", [])}
        )
        approved = (
            ids
            if decision.get("approved") == "all"
            else [i for i in decision.get("approved", []) if i in ids]
        )
        return {"approval": {"approved": approved, "notes": decision.get("notes")},
                "events": [f"approval: {approved or 'none'}"]}  # fmt: skip

    def memo(state: FrontOfficeState) -> dict:
        return {"memo": specialists.write_memo(deps, state)} | deps.flush("gm: memo written")

    def answer_stats(state: FrontOfficeState) -> dict:
        text, attempts = stats_analyst.answer_question(deps, state["request"])
        return {"answer": text, "sql_attempts": attempts} | deps.flush("stats: answered")

    def answer_player(state: FrontOfficeState) -> dict:
        if not state.get("player"):
            return {
                "error": "Name the player you are asking about.",
                "events": ["stopped: no player"],
            }
        return {
            "answer": specialists.answer_player(deps, state["request"], state["player"])
        } | deps.flush("gm: answered")

    g = StateGraph(FrontOfficeState)
    for name, fn in [("router", router), ("need_team", need_team), ("gm_plan", gm_plan), ("stats", stats),
                     ("valuation", valuation), ("scout", scout), ("cap", cap), ("devils_advocate", devils_advocate),
                     ("approval", approval), ("memo", memo), ("answer_stats", answer_stats),
                     ("answer_player", answer_player)]:  # fmt: skip
        g.add_node(name, traced_node(name, fn))
    g.add_edge(START, "router")
    g.add_conditional_edges("router", after_router, {"trade_search": "gm_plan", "need_team": "need_team",
                                                     "stats_question": "answer_stats", "player_question": "answer_player"})  # fmt: skip
    g.add_edge("gm_plan", "stats")
    g.add_edge("stats", "valuation")
    g.add_edge("valuation", "scout")
    g.add_edge("scout", "cap")
    if deps.devils_advocate:
        g.add_edge("cap", "devils_advocate")
        g.add_conditional_edges(
            "devils_advocate", after_critique, {"cap": "cap", "approval": "approval"}
        )
    else:
        g.add_edge("cap", "approval")
    g.add_edge("approval", "memo")
    for end in ("memo", "need_team", "answer_stats", "answer_player"):
        g.add_edge(end, END)

    checkpointer = None
    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = SqliteSaver(sqlite3.connect(str(checkpoint_path), check_same_thread=False))
    return g.compile(checkpointer=checkpointer)
