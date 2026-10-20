from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

from agents.providers import chat

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "nba_bench" / "trades.jsonl"
RESULTS = ROOT / "results"
CODES = [
    "SALARY_MATCHING", "SALARY_MATCHING_APRON", "ABSORB_WITHOUT_ROOM", "SECOND_APRON_AGGREGATION",
    "SECOND_APRON_CASH", "ROSTER_MAX", "ROSTER_MIN", "TWO_WAY_MAX", "STEPIEN", "PICK_OUT_OF_WINDOW",
    "PICK_NOT_OWNED", "RECENTLY_SIGNED", "AGGREGATION_TOO_SOON", "CASH_LIMIT", "TRADE_DEADLINE_PASSED",
]  # fmt: skip

SYSTEM = """You are an NBA salary cap expert checking whether a proposed trade is legal under the 2023 CBA.
Apply exactly these rules, using the numbers given in the case. All money is in US dollars.

Definitions: a team's payroll after the trade = payroll - outgoing salary + incoming salary.
Two-way contracts never count toward payroll or matching. Picks and cash carry no salary.

1. SALARY_MATCHING / SALARY_MATCHING_APRON / ABSORB_WITHOUT_ROOM. For each team with incoming salary,
   the maximum incoming salary is the LARGEST of:
   a) room path: salary_cap - payroll_before + outgoing
   b) expanded path: min( max( min(2*outgoing + cushion, outgoing + bracket), 1.25*outgoing + cushion ),
                          first_apron - payroll_before + outgoing )
   c) apron path: 100% of outgoing
   If incoming > maximum: code ABSORB_WITHOUT_ROOM when outgoing is 0, else SALARY_MATCHING_APRON when the
   payroll after the trade is above the first apron, else SALARY_MATCHING.
2. SECOND_APRON_AGGREGATION: a team whose payroll after the trade is above the second apron cannot send out
   two or more salaried players while taking back salary.
3. SECOND_APRON_CASH: a team whose payroll after the trade is above the second apron cannot send cash.
4. CASH_LIMIT: no team may send or receive more than cash_limit in one trade.
5. ROSTER_MAX: on or after regular_season_start a team may not end above max_standard standard contracts
   if the trade increases its count. TWO_WAY_MAX: at most max_two_way two-way contracts.
6. STEPIEN: when a team trades away a first-round pick for draft year Y, it may not be left (after the trade,
   using first_round_picks_owned_by_year adjusted for this trade) with zero first-round picks in both Y-1 and Y,
   or in both Y and Y+1, counting only tradable years. Gaps between other years that already existed before the
   trade are not violations.
7. PICK_NOT_OWNED: a team can only trade picks it currently owns (current_owner must equal the giver).
8. RECENTLY_SIGNED: a player signed on or after 2026-07-01 cannot be traded before the later of
   offseason_signing_trade_date and 3 months after signing. Earlier signings wait 3 months.
9. AGGREGATION_TOO_SOON: a player acquired by trade cannot be traded together with other salaried players
   within 60 days of that trade.
10. TRADE_DEADLINE_PASSED: no trades after trade_deadline.

Answer with JSON only: {"valid": true|false, "violations": [{"code": "<CODE>", "team": "<ABBR>"}],
"reasoning": "<one or two sentences>"}. Use only these codes: """ + ", ".join(CODES)


def render_case(case: dict) -> str:
    return "Check this trade:\n" + json.dumps(case["context"], indent=1)


def parse(text: str) -> dict | None:
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(d, dict) or not isinstance(d.get("valid"), bool):
        return None
    viol = d.get("violations") or []
    codes = sorted({v.get("code") for v in viol if isinstance(v, dict) and v.get("code")})
    return {"valid": d["valid"], "codes": codes, "reasoning": d.get("reasoning", "")}


def run(model: str, cases: list[dict], out_path: Path) -> list[dict]:
    done = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    with out_path.open("a", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            if case["id"] in done:
                continue
            res = chat(model, SYSTEM, render_case(case))
            row = {
                "id": case["id"], "bucket": case["bucket"], "raw": res.text, "parsed": parse(res.text),
                "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "seconds": round(res.seconds, 2),
            }  # fmt: skip
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            done[case["id"]] = row
            print(f"[{i}/{len(cases)}] {case['id']} {case['bucket']}: {row['parsed']}", flush=True)
    return [done[c["id"]] for c in cases]


def score(cases: list[dict], rows: list[dict]) -> dict:
    by_id = {c["id"]: c for c in cases}
    total = len(rows)
    parsed = [r for r in rows if r["parsed"]]
    correct = sum(r["parsed"]["valid"] == by_id[r["id"]]["expected"]["valid"] for r in parsed)
    invalid = [r for r in rows if not by_id[r["id"]]["expected"]["valid"]]
    valid = [r for r in rows if by_id[r["id"]]["expected"]["valid"]]
    false_valid = sum(1 for r in invalid if r["parsed"] and r["parsed"]["valid"])
    false_invalid = sum(1 for r in valid if r["parsed"] and not r["parsed"]["valid"])
    exact = 0
    tp = fp = fn = 0
    per_bucket = defaultdict(lambda: [0, 0])
    for r in rows:
        exp = by_id[r["id"]]["expected"]
        exp_codes = {c for c, _ in exp["violations"]}
        got = set(r["parsed"]["codes"]) if r["parsed"] else set()
        ok = bool(r["parsed"]) and r["parsed"]["valid"] == exp["valid"] and got == exp_codes
        exact += ok
        per_bucket[r["bucket"]][0] += ok
        per_bucket[r["bucket"]][1] += 1
        tp += len(got & exp_codes)
        fp += len(got - exp_codes)
        fn += len(exp_codes - got)
    return {
        "cases": total,
        "parse_failures": total - len(parsed),
        "verdict_accuracy": round(correct / total, 3),
        "exact_match": round(exact / total, 3),
        "error_rate": round(1 - exact / total, 3),
        "false_valid_rate": round(false_valid / max(1, len(invalid)), 3),
        "false_invalid_rate": round(false_invalid / max(1, len(valid)), 3),
        "code_precision": round(tp / max(1, tp + fp), 3),
        "code_recall": round(tp / max(1, tp + fn), 3),
        "per_bucket_exact": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per_bucket.items())},
        "avg_seconds": round(sum(r["seconds"] for r in rows) / total, 2),
        "avg_input_tokens": round(sum(r["input_tokens"] for r in rows) / total),
        "avg_output_tokens": round(sum(r["output_tokens"] for r in rows) / total),
        "predicted_codes": dict(Counter(c for r in parsed for c in r["parsed"]["codes"])),
    }


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Compare an LLM against the rules engine on trade legality"
    )
    parser.add_argument(
        "--model", required=True, help="e.g. ollama:llama3.1:8b or groq:llama-3.3-70b-versatile"
    )
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines()][
        : args.limit
    ]
    RESULTS.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9.-]+", "_", args.model)
    rows = run(args.model, cases, RESULTS / f"llm_vs_rules_{slug}.jsonl")
    summary = {"model": args.model, **score(cases, rows)}
    (RESULTS / f"llm_vs_rules_{slug}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
