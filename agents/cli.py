from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from langgraph.types import Command

from agents import tracing
from agents.deps import Deps
from agents.graph import build
from agents.llm import cost_report
from data.config import ROOT

RUNS = ROOT / "runs"


def _fmt_money(v: float | None) -> str:
    return "n/a" if v is None else f"${v / 1e6:,.1f}M"


def show_proposals(payload: dict) -> None:
    crit = {c["proposal_id"]: c for c in payload.get("critiques", [])}
    if not payload.get("proposals"):
        print("\nNo legal proposal satisfied the brief.")
    for p in payload.get("proposals", []):
        send = ", ".join(x["name"] for x in p["send_players"]) or "-"
        picks = ", ".join(x["asset_id"] for x in p["send_picks"]) or "no picks"
        v = p["value"]
        print(
            f"\n[{p['id']}] receive {p['receive']['name']} ({p['from_team']}) for {send}; {picks}"
        )
        print(f"     WS change {v['ws_change_for_us']:+.1f}, our value {_fmt_money(v['our_value_change'])}, "
              f"their value {_fmt_money(v['counterparty_value_change'])}")  # fmt: skip
        c = crit.get(p["id"])
        if c:
            print(f"     devil's advocate: {c['verdict']} - {c['reasoning'][:220]}")


def ask_approval(payload: dict, auto: bool) -> dict:
    show_proposals(payload)
    if auto or not payload.get("proposals"):
        dropped = {c["proposal_id"] for c in payload.get("critiques", []) if c["verdict"] == "drop"}
        kept = [p["id"] for p in payload.get("proposals", []) if p["id"] not in dropped]
        return {
            "approved": kept,
            "notes": "auto-approved: proposals the devil's advocate did not drop" if auto else None,
        }
    raw = input("\nApprove which proposals? (e.g. P1,P3 / all / none): ").strip()
    notes = input("Notes for the memo (optional): ").strip() or None
    approved = (
        "all"
        if raw.lower() == "all"
        else [x.strip().upper() for x in raw.split(",") if x.strip() and raw.lower() != "none"]
    )
    return {"approved": approved, "notes": notes}


def run(graph, inputs, config: dict, auto: bool) -> dict:
    payload = inputs
    while True:
        interrupted = None
        for update in graph.stream(payload, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    interrupted = delta[0].value
                    continue
                for e in (delta or {}).get("events", []):
                    print(f"  - {e}")
        if interrupted is None:
            return graph.get_state(config).values
        payload = Command(resume=ask_approval(interrupted, auto))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Front Office agents")
    parser.add_argument("request", nargs="?", help="What you want, in plain language")
    parser.add_argument("--team", help="Your team abbreviation, e.g. BOS")
    parser.add_argument("--date", help="Trade date (ISO); defaults to today")
    parser.add_argument("--thread", help="Resume or name a conversation thread")
    parser.add_argument("--auto-approve", action="store_true", help="Skip the human approval step")
    parser.add_argument("--no-devils-advocate", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.INFO)

    deps = Deps(devils_advocate=not args.no_devils_advocate)
    graph = build(deps)
    thread = args.thread or uuid.uuid4().hex[:8]
    config = {"configurable": {"thread_id": thread}}
    existing = graph.get_state(config)
    if existing.next:
        print(f"Resuming thread {thread} at {existing.next}")
        inputs = None
        if existing.interrupts:
            inputs = Command(resume=ask_approval(existing.interrupts[0].value, args.auto_approve))
    elif args.request:
        inputs = {"request": args.request, "team": args.team, "trade_date": args.date}
        print(f"Thread {thread}")
    else:
        sys.exit("Give a request, or --thread of an unfinished run.")

    request = args.request or existing.values.get("request", "")
    team = args.team or existing.values.get("team") or "no-team"
    tags = [f"team:{team}", "approval:auto" if args.auto_approve else "approval:human",
            f"devils_advocate:{'on' if deps.devils_advocate else 'off'}"]  # fmt: skip
    models = {
        role: deps.llm.model_for(role)
        for role in ("router", "gm", "stats", "scout", "devils_advocate", "memo")
    }
    with tracing.run_trace("front-office", thread, tags, models, request) as root:
        state = run(graph, inputs, config, args.auto_approve)
        trace_id = tracing.current_trace_id()
        root.update(
            output=state.get("memo")
            or state.get("answer")
            or state.get("error")
            or "waiting for approval"
        )
    if trace_id:
        host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
        print(f"Trace: {host}/project/front-office/traces/{trace_id}")
    if state.get("error"):
        print(f"\n{state['error']}")
    if state.get("answer"):
        print(f"\n{state['answer']}")
    if state.get("memo"):
        print(f"\n{state['memo']}")
    report = cost_report(state.get("usage", []))
    t = report["total"]
    print(f"\n{t['calls']} LLM calls, {t['input_tokens'] + t['output_tokens']:,} tokens, {t['seconds']:.0f}s of model time, "
          f"~${t['usd']:.4f} at list prices")  # fmt: skip
    RUNS.mkdir(exist_ok=True)
    out = Path(RUNS / f"{datetime.now(UTC):%Y%m%dT%H%M%S}_{thread}.json")
    out.write_text(
        json.dumps(
            state | {"cost": report, "thread": thread, "trace_id": trace_id}, indent=1, default=str
        ),
        encoding="utf-8",
    )
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
