from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from agents import tracing
from agents.deps import Deps
from agents.graph import build
from agents.llm import LLM, cost_report

ROLES = ("router", "gm", "stats", "scout", "devils_advocate", "memo")


@dataclass
class Run:
    thread: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    devils_advocate: bool = True
    request: str = ""
    team: str | None = None
    events: list[str] = field(default_factory=list)
    pending: dict | None = None
    state: dict = field(default_factory=dict)
    trace_ids: list[str] = field(default_factory=list)

    @property
    def config(self) -> dict:
        return {"configurable": {"thread_id": self.thread}}

    @property
    def finished(self) -> bool:
        return self.pending is None and bool(
            self.state.get("memo") or self.state.get("answer") or self.state.get("error")
        )


def make_graph(devils_advocate: bool, deps: Deps | None = None, **kw):
    return build(deps or Deps(devils_advocate=devils_advocate), **kw)


def _stream(graph, payload, config: dict) -> Iterator[tuple[str, Any]]:
    for update in graph.stream(payload, config, stream_mode="updates"):
        for node, delta in update.items():
            if node == "__interrupt__":
                yield "interrupt", delta[0].value
                continue
            for e in (delta or {}).get("events", []):
                yield "event", e


def step(run: Run, graph, payload) -> Iterator[str]:
    tags = [f"team:{run.team or 'no-team'}", "approval:human", "ui:streamlit",
            f"devils_advocate:{'on' if run.devils_advocate else 'off'}"]  # fmt: skip
    llm = LLM()
    models = {role: llm.model_for(role) for role in ROLES}
    run.pending = None
    with tracing.run_trace("front-office", run.thread, tags, models, run.request) as root:
        for kind, value in _stream(graph, payload, run.config):
            if kind == "interrupt":
                run.pending = value
            else:
                run.events.append(value)
                yield value
        run.state = graph.get_state(run.config).values
        trace_id = tracing.current_trace_id()
        root.update(output=run.state.get("memo") or run.state.get("answer")
                    or run.state.get("error") or "waiting for approval")  # fmt: skip
    if trace_id:
        run.trace_ids.append(trace_id)


def start(run: Run, graph, trade_date: str | None) -> Iterator[str]:
    payload = {"request": run.request, "team": run.team, "trade_date": trade_date}
    yield from step(run, graph, payload)


def resume(run: Run, graph, approved: list[str], notes: str | None) -> Iterator[str]:
    yield from step(run, graph, Command(resume={"approved": approved, "notes": notes or None}))


def load(thread: str, graph, devils_advocate: bool = True) -> Run | None:
    config = {"configurable": {"thread_id": thread}}
    snap = graph.get_state(config)
    if not snap.values:
        return None
    values = snap.values
    run = Run(thread=thread, devils_advocate=devils_advocate, request=values.get("request", ""),
              team=values.get("team"), events=list(values.get("events", [])), state=values)  # fmt: skip
    if snap.interrupts:
        run.pending = snap.interrupts[0].value
    return run


def default_selection(pending: dict) -> list[str]:
    dropped = {c["proposal_id"] for c in pending.get("critiques", []) if c["verdict"] == "drop"}
    return [p["id"] for p in pending.get("proposals", []) if p["id"] not in dropped]


def costs(state: dict) -> dict:
    return cost_report(state.get("usage", []))


def trace_url(trace_id: str) -> str:
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    return f"{host}/project/front-office/traces/{trace_id}"
