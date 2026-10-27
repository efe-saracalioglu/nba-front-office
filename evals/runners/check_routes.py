from __future__ import annotations

import argparse
import json
import logging
from collections import Counter

from agents.specialists import route
from data.config import ROOT
from evals.harness import RESULTS, load_jsonl, make_deps

BENCH = ROOT / "evals" / "nba_bench"
EXPECTED = {"exact": "stats_question", "scenarios": "trade_search"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the router on every NBA-Bench request")
    parser.add_argument("--config", default="full")
    args = parser.parse_args()
    logging.disable(logging.INFO)
    deps = make_deps(args.config)
    rows, confusion = [], Counter()
    for suite, expected in EXPECTED.items():
        for item in load_jsonl(BENCH / f"{suite}.jsonl"):
            text = item.get("question") or item["request"]
            got = route(deps, text).route
            confusion[(expected, got)] += 1
            if got != expected:
                rows.append({"id": item["id"], "expected": expected, "got": got, "text": text})
                print(f"{item['id']}: expected {expected}, got {got}", flush=True)
    total = sum(confusion.values())
    summary = {"config": args.config, "requests": total,
               "accuracy": round(1 - len(rows) / total, 3),
               "confusion": {f"{e} -> {g}": n for (e, g), n in sorted(confusion.items())},
               "misrouted": rows}  # fmt: skip
    (RESULTS / f"routes_{args.config}.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "misrouted"}, indent=2))


if __name__ == "__main__":
    main()
