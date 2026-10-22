from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data.config import ROOT
from evals.harness import load_jsonl
from rules.engine import validate_trade
from rules.models import Trade
from rules.state import load_league

TRADES = ROOT / "evals" / "nba_bench" / "trades.jsonl"


def trade_labels_still_hold(db_path: Path | None) -> list[str]:
    lg = load_league(db_path)
    drift = []
    for case in load_jsonl(TRADES):
        verdict = validate_trade(Trade.model_validate(case["trade"]), lg)
        got = sorted({(v.code, v.team) for v in verdict.violations})
        want = sorted(tuple(v) for v in case["expected"]["violations"])
        if verdict.valid != case["expected"]["valid"] or got != want:
            drift.append(
                f"{case['id']}: expected {want or 'valid'}, engine now says {got or 'valid'}"
            )
    return drift


def exact_gate(summary_path: Path, threshold: float) -> tuple[bool, str]:
    s = json.loads(summary_path.read_text(encoding="utf-8"))
    ok = s["accuracy"] >= threshold
    return (
        ok,
        f"exact-answer accuracy {s['accuracy']:.0%} on {s['questions']} questions (threshold {threshold:.0%})",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CI gates for NBA-Bench")
    parser.add_argument(
        "--trades", action="store_true", help="check rule-labelled trade cases against the engine"
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--exact-summary", type=Path)
    parser.add_argument("--threshold", type=float, default=0.7)
    args = parser.parse_args()
    lines, failed = [], False
    if args.trades:
        drift = trade_labels_still_hold(args.db)
        lines.append(
            f"rules engine agrees with {100 - len(drift)}/100 labelled trades"
            if not drift
            else "rule labels drifted:\n" + "\n".join(drift[:20])
        )
        failed |= bool(drift)
    if args.exact_summary:
        ok, msg = exact_gate(args.exact_summary, args.threshold)
        lines.append(msg)
        failed |= not ok
    report = "\n".join(lines)
    print(report)
    Path("eval_report.md").write_text(
        ("### NBA-Bench smoke: " + ("FAILED" if failed else "passed") + "\n\n" + report + "\n"),
        encoding="utf-8",
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
