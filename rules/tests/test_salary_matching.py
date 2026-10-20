import pytest

from rules.cba.salary_matching import expanded_matching_limit
from rules.tests.conftest import APRON1, CAP, SEASON, check, codes, league, leg, p, team

M = 1_000_000


@pytest.mark.parametrize(
    "outgoing, expected",
    [
        (0, 250_000),
        (5 * M, 10_250_000),
        (8_846_000, 17_942_000),
        (10 * M, 19_096_000),
        (30 * M, 39_096_000),
        (35_384_000, 44_480_000),
        (40 * M, 50_250_000),
        (60 * M, 75_250_000),
    ],
)
def test_expanded_matching_brackets(outgoing, expected):
    assert expanded_matching_limit(outgoing, SEASON) == expected


def _swap(payroll_a, out_a, in_a, payroll_b=180 * M):
    a_out, b_out = p("AAA", out_a), p("BBB", in_a)
    lg = league(team("AAA", payroll_a, a_out), team("BBB", payroll_b, b_out))
    return check(lg, leg("AAA", "BBB", [a_out]), leg("BBB", "AAA", [b_out]))


def test_over_cap_team_at_exact_limit_is_valid():
    v = _swap(180 * M, 10 * M, 19_096_000, payroll_b=190 * M)
    assert "SALARY_MATCHING" not in codes(v)


def test_over_cap_team_one_dollar_over_limit_fails():
    v = _swap(180 * M, 10 * M, 19_096_001, payroll_b=190 * M)
    assert codes(v) == ["SALARY_MATCHING"]
    bad = v.violations[0]
    assert bad.team == "AAA" and bad.details["allowed"] == 19_096_000


def test_under_cap_team_absorbs_into_room():
    incoming = p("BBB", 20 * M)
    lg = league(team("AAA", 120 * M), team("BBB", 180 * M, incoming))
    v = check(lg, leg("BBB", "AAA", [incoming]))
    assert v.valid, v.explain()
    aaa = next(t for t in v.teams if t.team == "AAA")
    assert aaa.payroll_after == 140 * M and aaa.status_after == "under_cap"


def test_absorbing_past_the_cap_without_sending_salary_fails():
    incoming = p("BBB", 50 * M)
    lg = league(team("AAA", 150 * M), team("BBB", 180 * M, incoming))
    v = check(lg, leg("BBB", "AAA", [incoming]))
    assert codes(v) == ["ABSORB_WITHOUT_ROOM"]


def test_under_cap_team_uses_room_plus_outgoing():
    v = _swap(150 * M, 10 * M, 24 * M)
    assert "SALARY_MATCHING" not in codes(v)
    v = _swap(150 * M, 10 * M, 30 * M)
    assert codes(v) == ["SALARY_MATCHING"]
    assert v.violations[0].details["allowed"] == CAP - 150 * M + 10 * M


def test_team_ending_above_first_apron_limited_to_100_percent():
    assert "SALARY_MATCHING_APRON" not in codes(_swap(215 * M, 20 * M, 20 * M))
    v = _swap(215 * M, 20 * M, 20 * M + 1)
    assert codes(v) == ["SALARY_MATCHING_APRON"]


def test_team_above_apron_can_shed_salary():
    assert "SALARY_MATCHING_APRON" not in codes(_swap(215 * M, 20 * M, 13 * M))


def test_expanded_matching_stops_at_first_apron():
    assert "SALARY_MATCHING" not in codes(_swap(200 * M, 10 * M, 19 * M))
    v = _swap(200 * M, 10 * M, 19_100_000)
    assert v.violations[0].details["allowed"] == APRON1 - 200 * M + 10 * M


def test_two_way_salary_does_not_count():
    tw = p("BBB", 600_000, is_two_way=True)
    a_out = p("AAA", 5 * M)
    b_out = p("BBB", 5 * M)
    lg = league(team("AAA", 180 * M, a_out), team("BBB", 180 * M, b_out, tw, two_way=1))
    v = check(lg, leg("AAA", "BBB", [a_out]), leg("BBB", "AAA", [b_out, tw]))
    aaa = next(t for t in v.teams if t.team == "AAA")
    assert aaa.incoming_salary == 5 * M


def test_summary_reports_max_incoming():
    v = _swap(180 * M, 10 * M, 12 * M, payroll_b=190 * M)
    aaa = next(t for t in v.teams if t.team == "AAA")
    assert aaa.max_incoming_salary == 19_096_000


def test_both_sides_checked_independently():
    v = _swap(215 * M, 30 * M, 10 * M, payroll_b=215 * M)
    assert [x.team for x in v.violations] == ["BBB"]
