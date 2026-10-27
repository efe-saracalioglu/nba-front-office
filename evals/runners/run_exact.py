from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict

from data.config import ROOT
from evals.harness import RESULTS, configs, load_jsonl, make_deps, run_graph, run_suite
from evals.scoring import check

ITEMS = ROOT / "evals" / "nba_bench" / "exact.jsonl"
EVAL_DATE = "2026-12-20"


def answer_with(config_name: str, question: str, item_id: str) -> dict:
    if configs()[config_name].get("single_agent"):
        from agents.single_agent import run_single_agent

        return run_single_agent(
            question,
            None,
            EVAL_DATE,
            tags=["suite:exact", f"config:{config_name}"],
            session=f"exact-{item_id}",
        )
    deps = make_deps(config_name)
    out = run_graph(
        deps,
        question,
        None,
        EVAL_DATE,
        ["suite:exact", f"config:{config_name}"],
        f"exact-{item_id}",
    )
    s = out.pop("state")
    attempts = s.get("sql_attempts", [])
    return out | {
        "answer": s.get("answer"),
        "route": s.get("route"),
        "sql_attempts": len([a for a in attempts if a["attempt"] != "fallback"]),
        "sql_first_try_ok": bool(attempts and attempts[0]["ok"]),
    }


def scored(item: dict, out: dict) -> dict:
    ok, why = check(item, out.get("answer"))
    return out | {
        "correct": ok,
        "why": why,
        "verdict": "correct" if ok else f"wrong ({why})",
        "template": item["template"],
    }


def run_one(item: dict, config_name: str) -> dict:
    return scored(item, answer_with(config_name, item["question"], item["id"]))


def rescore(config_name: str, items: list[dict]) -> list[dict]:
    path = RESULTS / "exact" / f"{config_name}.jsonl"
    by_id = {i["id"]: i for i in items}
    rows = [scored(by_id[r["id"]], r) for r in load_jsonl(path) if r["id"] in by_id]
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
        encoding="utf-8",
    )
    return rows


def summarize(rows: list[dict]) -> dict:
    by_template = defaultdict(lambda: [0, 0])
    for r in rows:
        by_template[r["template"]][0] += r["correct"]
        by_template[r["template"]][1] += 1
    n = len(rows)
    return {
        "questions": n,
        "accuracy": round(sum(r["correct"] for r in rows) / n, 3),
        "routed_to_stats": round(sum(r.get("route") == "stats_question" for r in rows) / n, 3),
        "sql_first_try_ok": round(sum(bool(r.get("sql_first_try_ok")) for r in rows) / n, 3),
        "avg_sql_attempts": round(sum(r.get("sql_attempts") or 0 for r in rows) / n, 2),
        "errors": sum(bool(r.get("error")) for r in rows),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 1),
        "avg_tokens": round(
            sum(r["cost"]["input_tokens"] + r["cost"]["output_tokens"] for r in rows) / n
        ),
        "total_usd_list_price": round(sum(r["cost"]["usd"] for r in rows), 4),
        "by_template": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_template.items())},
        "routes": dict(Counter(r.get("route") for r in rows)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the exact-answer layer of NBA-Bench")
    parser.add_argument("--config", default="full")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="only questions answerable on the sample warehouse",
    )
    parser.add_argument(
        "--rescore", action="store_true", help="re-score saved answers without calling any model"
    )
    args = parser.parse_args()
    logging.disable(logging.INFO)
    items = load_jsonl(ITEMS)
    if args.sample_only:
        items = [i for i in items if i["sample_ok"]]
    items = items[: args.limit]
    rows = (
        rescore(args.config, items)
        if args.rescore
        else run_suite("exact", args.config, items, run_one)
    )
    summary = {"config": args.config, **summarize(rows)}
    out = RESULTS / "exact" / f"{args.config}_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
