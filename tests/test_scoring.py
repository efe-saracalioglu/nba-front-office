import pytest

from evals.scoring import check, numbers


def test_numbers_ignore_seasons_and_years_and_scale_money():
    assert numbers("In 2025-26 he made $58.5M, up from 2024 when he made 40 million") == [
        58_500_000.0,
        40_000_000.0,
    ]
    assert numbers("They won 26 games in 2024-25.") == [26.0]


@pytest.mark.parametrize(
    "item, answer, ok",
    [
        (
            {
                "kind": "number",
                "question": "How many games did X win in 2024-25?",
                "answer": 26,
                "tolerance": 0,
            },
            "They finished 2025-26 with 41 wins.",
            False,
        ),
        (
            {
                "kind": "number",
                "question": "How many games did X win in 2024-25?",
                "answer": 26,
                "tolerance": 0,
            },
            "The team won 26 games.",
            True,
        ),
        (
            {
                "kind": "number",
                "question": "How many players averaged at least 25 points (minimum 50 games)?",
                "answer": 13,
                "tolerance": 0,
            },
            "13 players averaged 25+ over 50 games.",
            True,
        ),
        (
            {
                "kind": "number",
                "question": "How many players averaged at least 25 points (minimum 50 games)?",
                "answer": 13,
                "tolerance": 0,
            },
            "25 players did.",
            False,
        ),
        (
            {
                "kind": "money",
                "question": "What is the payroll?",
                "answer": 222650306,
                "tolerance_pct": 0.01,
            },
            "About $222.7M.",
            True,
        ),
        (
            {
                "kind": "money",
                "question": "What is the payroll?",
                "answer": 222650306,
                "tolerance_pct": 0.01,
            },
            "$230 million",
            False,
        ),
        (
            {"kind": "number", "question": "PPG?", "answer": 17.6, "tolerance": 0.15},
            "He averaged 17.55 points.",
            True,
        ),
        (
            {"kind": "name", "question": "Who led?", "answer": "Nikola Jokić"},
            "Nikola Jokic led the league.",
            True,
        ),
        ({"kind": "name", "question": "Who led?", "answer": "Nikola Jokić"}, "Jokic led.", False),
        (
            {
                "kind": "team",
                "question": "Which team?",
                "answer": "Utah Jazz",
                "aliases": ["UTA", "Jazz"],
            },
            "It belongs to UTA.",
            True,
        ),
        (
            {
                "kind": "text",
                "question": "Status?",
                "answer": "Day-To-Day",
                "aliases": ["Day To Day"],
            },
            "He is listed as day-to-day.",
            True,
        ),
    ],
)
def test_check(item, answer, ok):
    assert check(item, answer)[0] is ok


def test_check_handles_empty_answer():
    assert check({"kind": "name", "question": "q", "answer": "A B"}, None) == (False, "no answer")


def test_check_accepts_unicode_dashes():
    item = {
        "kind": "text",
        "question": "Status?",
        "answer": "Day-To-Day",
        "aliases": ["Day To Day"],
    }
    assert check(item, "Collin Sexton’s current injury status is Day‑To‑Day.")[0]


def test_markdown_bold_does_not_hide_a_match():
    item = {"kind": "name", "answer": "Nikola Jokić"}
    assert check(item, "The center is **Nikola Jokić**, projected at 11.5 WS.")[0]
    status = {"kind": "text", "answer": "Day-To-Day", "aliases": ["Day To Day"]}
    assert check(status, "He is listed as **Day‑To‑Day** with a shoulder issue.")[0]
    assert not check({"kind": "name", "answer": "Jalen Williams"}, "**Jaylin Williams**")[0]
