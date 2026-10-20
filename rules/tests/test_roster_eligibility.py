from datetime import date

import pytest

from rules.cba.eligibility import add_months, tradable_from
from rules.state import parse_how_acquired
from rules.tests.conftest import SEASON, check, codes, league, leg, p, team, warning_codes

M = 1_000_000


def _two_for_one(standard_b: int, day=date(2026, 11, 1)):
    a1, a2, b = p("AAA", 3 * M), p("AAA", 3 * M), p("BBB", 6 * M)
    lg = league(
        team("AAA", 150 * M, a1, a2, standard=14), team("BBB", 150 * M, b, standard=standard_b)
    )
    return check(lg, leg("AAA", "BBB", [a1, a2]), leg("BBB", "AAA", [b]), day=day)


def test_roster_full_team_cannot_take_two_for_one():
    assert "ROSTER_MAX" in codes(_two_for_one(15))


def test_roster_with_space_can_take_two_for_one():
    v = _two_for_one(14)
    assert "ROSTER_MAX" not in codes(v)


def test_offseason_roster_limit_is_21():
    assert "ROSTER_MAX" not in codes(_two_for_one(15, day=date(2026, 8, 1)))
    assert "ROSTER_MAX" in codes(_two_for_one(21, day=date(2026, 8, 1)))


def test_team_already_over_limit_not_flagged_if_not_growing():
    a, b = p("AAA", 3 * M), p("BBB", 3 * M)
    lg = league(team("AAA", 150 * M, a, standard=16), team("BBB", 150 * M, b))
    assert "ROSTER_MAX" not in codes(check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b])))


def test_dropping_to_13_is_a_warning():
    v = _two_for_one(14)
    assert "ROSTER_BELOW_MIN" in warning_codes(v)
    assert v.valid


def test_dropping_below_13_is_an_error():
    a1, a2, b = p("AAA", 3 * M), p("AAA", 3 * M), p("BBB", 6 * M)
    lg = league(team("AAA", 150 * M, a1, a2, standard=13), team("BBB", 150 * M, b, standard=13))
    v = check(lg, leg("AAA", "BBB", [a1, a2]), leg("BBB", "AAA", [b]))
    assert "ROSTER_MIN" in codes(v)


def test_roster_minimum_ignored_in_offseason():
    a1, a2, b = p("AAA", 3 * M), p("AAA", 3 * M), p("BBB", 6 * M)
    lg = league(team("AAA", 150 * M, a1, a2, standard=12), team("BBB", 150 * M, b, standard=13))
    v = check(lg, leg("AAA", "BBB", [a1, a2]), leg("BBB", "AAA", [b]), day=date(2026, 8, 1))
    assert "ROSTER_MIN" not in codes(v) and "ROSTER_BELOW_MIN" not in warning_codes(v)


def test_two_way_limit():
    tw = p("AAA", 600_000, is_two_way=True)
    lg = league(team("AAA", 150 * M, tw, two_way=1), team("BBB", 150 * M, two_way=3))
    v = check(lg, leg("AAA", "BBB", [tw]), leg("BBB", "AAA", picks=["2030-2-BBB"]))
    assert codes(v) == ["TWO_WAY_MAX"]


@pytest.mark.parametrize(
    "start, months, expected",
    [
        (date(2026, 7, 10), 3, date(2026, 10, 10)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 12, 31), 2, date(2027, 2, 28)),
        (date(2027, 11, 30), 3, date(2028, 2, 29)),
    ],
)
def test_add_months(start, months, expected):
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    "signed, expected",
    [
        (date(2026, 7, 10), date(2026, 12, 15)),
        (date(2026, 9, 25), date(2026, 12, 25)),
        (date(2026, 3, 4), date(2026, 6, 4)),
        (None, None),
    ],
)
def test_tradable_from(signed, expected):
    assert tradable_from(p("AAA", 1 * M, signed_on=signed), SEASON) == expected


def _signed(signed_on, day):
    a, b = p("AAA", 5 * M, signed_on=signed_on, name="New Guy"), p("BBB", 5 * M)
    lg = league(team("AAA", 150 * M, a), team("BBB", 150 * M, b))
    return check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]), day=day)


def test_offseason_signee_blocked_until_december_15():
    v = _signed(date(2026, 7, 10), date(2026, 12, 14))
    assert codes(v) == ["RECENTLY_SIGNED"]
    assert "2026-12-15" in v.violations[0].message
    assert _signed(date(2026, 7, 10), date(2026, 12, 15)).valid


def test_late_signee_waits_three_months():
    assert codes(_signed(date(2026, 9, 25), date(2026, 12, 20))) == ["RECENTLY_SIGNED"]
    assert _signed(date(2026, 9, 25), date(2026, 12, 25)).valid


def test_last_season_signee_is_tradable():
    assert _signed(date(2026, 3, 4), date(2026, 11, 1)).valid


def _aggregate_recent(acquired, day, n_out=2):
    outs = [p("AAA", 5 * M, acquired_by_trade_on=acquired)] + [
        p("AAA", 5 * M) for _ in range(n_out - 1)
    ]
    b = p("BBB", 5 * M * n_out)
    lg = league(team("AAA", 150 * M, *outs), team("BBB", 150 * M, b))
    return check(lg, leg("AAA", "BBB", outs), leg("BBB", "AAA", [b]), day=day)


def test_recently_acquired_player_cannot_be_aggregated():
    assert codes(_aggregate_recent(date(2026, 10, 1), date(2026, 11, 15))) == [
        "AGGREGATION_TOO_SOON"
    ]


def test_aggregation_allowed_after_two_months():
    assert _aggregate_recent(date(2026, 10, 1), date(2026, 11, 30)).valid


def test_recently_acquired_player_can_be_traded_alone():
    assert _aggregate_recent(date(2026, 10, 1), date(2026, 10, 15), n_out=1).valid


@pytest.mark.parametrize(
    "text, signed, traded",
    [
        ("Signed on 07/22/26", date(2026, 7, 22), None),
        ("Traded from BOS on 02/05/26", None, date(2026, 2, 5)),
        ("Draft Rights Traded from ORL on 06/26/25", None, None),
        ("#40 Pick in 2026 Draft", None, None),
        ("Awarded on Waivers on 10/17/26", date(2026, 10, 17), None),
        (None, None, None),
    ],
)
def test_parse_how_acquired(text, signed, traded):
    assert parse_how_acquired(text) == (signed, traded)
