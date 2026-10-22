from __future__ import annotations

import json
from pathlib import Path

from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

from evals.judge import DIMENSIONS

HERE = Path(__file__).resolve().parent


def agreement(items: list[dict], labels: dict) -> dict:
    out = {}
    for d in DIMENSIONS:
        pairs = [
            (labels[i["item_id"]][d], i["judge"][d])
            for i in items
            if d in labels.get(i["item_id"], {})
        ]
        if len(pairs) < 3:
            continue
        human, judge = zip(*pairs, strict=True)
        out[d] = {
            "n": len(pairs),
            "spearman": round(float(spearmanr(human, judge).statistic), 3),
            "weighted_kappa": round(
                float(cohen_kappa_score(human, judge, weights="quadratic", labels=[1, 2, 3, 4, 5])),
                3,
            ),
            "exact_agreement": round(sum(h == j for h, j in pairs) / len(pairs), 3),
            "within_one": round(sum(abs(h - j) <= 1 for h, j in pairs) / len(pairs), 3),
            "judge_minus_human_mean": round(sum(j - h for h, j in pairs) / len(pairs), 2),
        }
    return out


def main() -> None:
    items = json.loads((HERE / "items.json").read_text(encoding="utf-8"))
    labels = json.loads((HERE / "labels.json").read_text(encoding="utf-8"))
    result = agreement(items, labels)
    (HERE / "agreement.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
