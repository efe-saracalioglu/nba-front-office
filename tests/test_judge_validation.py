from evals.judge_validation import group, validate


def row(judge, reply="memo", checked=None, error=None):
    scores = dict.fromkeys(("goal_fit", "realism", "grounding", "risk_awareness", "overall"), judge)
    return {"reply": reply, "checked": checked or [], "error": error, "judge": scores}


def proposal(ok, failed=()):
    return {"passes_all": ok, "failed_checks": list(failed)}


def test_groups():
    assert group(row(1, reply="")) == "empty_or_error"
    assert group(row(1, error="boom")) == "empty_or_error"
    assert group(row(3)) == "no_trade_reply"
    assert group(row(4, checked=[proposal(True)])) == "all_pass"
    assert group(row(2, checked=[proposal(True), proposal(False)])) == "some_fail"


def test_a_judge_that_tracks_the_checks_scores_well():
    data = [row(1, reply="")] + [row(5, checked=[proposal(True)]) for _ in range(3)]
    data += [row(1, checked=[proposal(False, ["improves_us"])]) for _ in range(3)]
    data = [r | {"group": group(r)} for r in data]
    out = validate(data)
    assert out["empty_scored_1"] == 1.0
    assert out["auc_all_pass_vs_some_fail"]["overall"] == 1.0
    assert out["worsens_us"] == {"n": 3, "goal_fit": 1}
