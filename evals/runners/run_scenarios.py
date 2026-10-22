from __future__ import annotations

import argparse
import json
import logging
import statistics

from data.config import ROOT
from evals.checks import check_output
from evals.harness import RESULTS, configs, load_jsonl, make_deps, run_graph, run_suite
from evals.judge import DIMENSIONS, attach_scores, judge

ITEMS = ROOT / "evals" / "nba_bench" / "scenarios.jsonl"
EVAL_DATE = "2026-12-20"


def produce(config_name: str, s: dict) -> dict:
    tags = ["suite:scenarios", f"config:{config_name}", f"team:{s['team']}"]
    if configs()[config_name].get("single_agent"):
        from agents.single_agent import run_single_agent

        out = run_single_agent(
            s["request"], s["team"], EVAL_DATE, tags=tags, session=f"{s['id']}-{config_name}"
        )
        return out | {
            "reply": out.pop("answer"),
            "proposals": [p.get("legs", []) for p in out.pop("proposals_raw")],
        }
    deps = make_deps(config_name)
    out = run_graph(deps, s["request"], s["team"], EVAL_DATE, tags, f"{s['id']}-{config_name}")
    st = out.pop("state")
    approved = set((st.get("approval") or {}).get("approved", []))
    proposals = [p["legs"] for p in st.get("proposals", []) if p["id"] in approved]
    return out | {"reply": st.get("memo") or st.get("answer") or "", "proposals": proposals, "route": st.get("route"),
                  "sql_attempts": len(st.get("sql_attempts", [])), "revisions": st.get("revisions", 0)}  # fmt: skip


def run_one(s: dict, config_name: str) -> dict:
    out = produce(config_name, s)
    checked = check_output(out["proposals"], s["team"], s["checks"], EVAL_DATE)
    scores = judge(s, out["reply"], checked)
    attach_scores(out.get("trace_id"), scores)
    passing = sum(c["passes_all"] for c in checked)
    verdict = (
        f"{len(checked)} proposals, {passing} pass all checks, judge overall {scores['overall']}"
    )
    return out | {
        "checked": checked,
        "judge": scores,
        "verdict": verdict,
        "hard": s.get("hard", False),
    }


def summarize(rows: list[dict]) -> dict:
    proposals = [c for r in rows for c in r["checked"]]
    failed = {}
    for c in proposals:
        for f in c["failed_checks"]:
            failed[f] = failed.get(f, 0) + 1
    n = len(rows)
    return {
        "scenarios": n,
        "with_proposals": sum(bool(r["checked"]) for r in rows),
        "proposals": len(proposals),
        "proposal_legal_rate": round(
            sum(c["legal"] for c in proposals) / max(1, len(proposals)), 3
        ),
        "proposal_pass_all_rate": round(
            sum(c["passes_all"] for c in proposals) / max(1, len(proposals)), 3
        ),
        "failed_checks": dict(sorted(failed.items(), key=lambda kv: -kv[1])),
        "judge_mean": {
            d: round(statistics.mean(r["judge"][d] for r in rows), 2) for d in DIMENSIONS
        },
        "errors": sum(bool(r.get("error")) for r in rows),
        "avg_seconds": round(statistics.mean(r["seconds"] for r in rows), 1),
        "avg_tokens": round(
            statistics.mean(r["cost"]["input_tokens"] + r["cost"]["output_tokens"] for r in rows)
        ),
        "avg_usd_list_price": round(statistics.mean(r["cost"]["usd"] for r in rows), 5),
        "avg_tool_calls": round(statistics.mean(r["tool_calls"] for r in rows), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the open-ended scenario layer of NBA-Bench")
    parser.add_argument("--config", default="full")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    logging.disable(logging.INFO)
    items = load_jsonl(ITEMS)
    if args.ids:
        items = [i for i in items if i["id"] in args.ids]
    items = items[: args.limit]
    rows = run_suite("scenarios", args.config, items, run_one)
    summary = {"config": args.config, **summarize(rows)}
    (RESULTS / "scenarios" / f"{args.config}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
