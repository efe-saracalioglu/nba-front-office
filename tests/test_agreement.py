from evals.human_labels.agreement import agreement


def test_agreement_perfect_and_biased():
    items = [{"item_id": f"H{i}", "judge": {d: s for d in ("goal_fit", "realism", "grounding", "risk_awareness", "overall")}}
             for i, s in enumerate([1, 2, 3, 4, 5])]  # fmt: skip
    same = {f"H{i}": {"overall": s} for i, s in enumerate([1, 2, 3, 4, 5])}
    r = agreement(items, same)["overall"]
    assert r["spearman"] == 1.0 and r["weighted_kappa"] == 1.0 and r["exact_agreement"] == 1.0
    lower = {f"H{i}": {"overall": max(1, s - 1)} for i, s in enumerate([1, 2, 3, 4, 5])}
    r = agreement(items, lower)["overall"]
    assert r["within_one"] == 1.0 and r["judge_minus_human_mean"] > 0
