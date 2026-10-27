from __future__ import annotations

import json
import statistics

from scipy.stats import mannwhitneyu, spearmanr

from evals.harness import RESULTS, load_jsonl
from evals.judge import DIMENSIONS

CONFIGS = ["full", "no_devils_advocate", "small_models", "single_agent"]
OUT = RESULTS / "judge_validation.json"


def group(row: dict) -> str:
    if row.get("error") or not (row.get("reply") or "").strip():
        return "empty_or_error"
    checked = row.get("checked") or []
    if not checked:
        return "no_trade_reply"
    return "all_pass" if all(c["passes_all"] for c in checked) else "some_fail"


def rows() -> list[dict]:
    out = []
    for cfg in CONFIGS:
        path = RESULTS / "scenarios" / f"{cfg}.jsonl"
        if path.exists():
            out += [r | {"group": group(r)} for r in load_jsonl(path)]
    return out


def auc(high: list[int], low: list[int]) -> float | None:
    if not high or not low:
        return None
    u = mannwhitneyu(high, low, alternative="two-sided").statistic
    return round(float(u) / (len(high) * len(low)), 3)


def validate(data: list[dict]) -> dict:
    groups = {}
    for g in ("empty_or_error", "no_trade_reply", "all_pass", "some_fail"):
        sub = [r for r in data if r["group"] == g]
        if sub:
            groups[g] = {"n": len(sub)} | {
                d: round(statistics.mean(r["judge"][d] for r in sub), 2) for d in DIMENSIONS
            }
    empty = [r for r in data if r["group"] == "empty_or_error"]
    with_props = [r for r in data if r["group"] in ("all_pass", "some_fail")]
    pass_share = [statistics.mean(c["passes_all"] for c in r["checked"]) for r in with_props]
    fails_improves = [
        r for r in with_props if any("improves_us" in c["failed_checks"] for c in r["checked"])
    ]
    return {
        "replies": len(data),
        "groups": groups,
        "empty_scored_1": round(
            sum(r["judge"]["overall"] == 1 for r in empty) / max(1, len(empty)), 3
        ),
        "auc_all_pass_vs_some_fail": {
            d: auc(
                [r["judge"][d] for r in with_props if r["group"] == "all_pass"],
                [r["judge"][d] for r in with_props if r["group"] == "some_fail"],
            )
            for d in ("goal_fit", "grounding", "overall")
        },
        "spearman_pass_share_vs_goal_fit": round(
            float(spearmanr(pass_share, [r["judge"]["goal_fit"] for r in with_props]).statistic), 3
        )
        if len(with_props) > 2
        else None,
        "worsens_us": {
            "n": len(fails_improves),
            "goal_fit": round(statistics.mean(r["judge"]["goal_fit"] for r in fails_improves), 2)
            if fails_improves
            else None,
        },
    }


def main() -> None:
    result = validate(rows())
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
