import json

from evals.runners.llm_vs_rules import parse, score


def test_parse_plain_json():
    out = parse(
        '{"valid": false, "violations": [{"code": "STEPIEN", "team": "BOS"}], "reasoning": "x"}'
    )
    assert out == {"valid": False, "codes": ["STEPIEN"], "reasoning": "x"}


def test_parse_json_inside_text():
    assert parse('Sure: {"valid": true, "violations": []} done')["valid"] is True


def test_parse_rejects_missing_verdict():
    assert parse('{"violations": []}') is None
    assert parse("not json") is None


def _case(i, valid, codes):
    return {"id": f"c{i}", "bucket": "VALID" if valid else codes[0],
            "expected": {"valid": valid, "violations": [[c, "AAA"] for c in codes]}}  # fmt: skip


def _row(i, parsed):
    return {
        "id": f"c{i}",
        "bucket": "",
        "parsed": parsed,
        "seconds": 1.0,
        "input_tokens": 10,
        "output_tokens": 5,
    }


def test_score_counts_false_valid_and_exact_match():
    cases = [_case(1, True, []), _case(2, False, ["STEPIEN"]), _case(3, False, ["CASH_LIMIT"])]
    for c, r in zip(cases, ["VALID", "STEPIEN", "CASH_LIMIT"], strict=True):
        c["bucket"] = r
    rows = [
        _row(1, {"valid": True, "codes": []}),
        _row(2, {"valid": True, "codes": []}),
        _row(3, {"valid": False, "codes": ["SALARY_MATCHING"]}),
    ]
    for r, c in zip(rows, cases, strict=True):
        r["bucket"] = c["bucket"]
    s = score(cases, rows)
    assert s["verdict_accuracy"] == round(2 / 3, 3)
    assert s["exact_match"] == round(1 / 3, 3)
    assert s["false_valid_rate"] == 0.5
    assert s["code_recall"] == 0.0
    assert json.dumps(s)
