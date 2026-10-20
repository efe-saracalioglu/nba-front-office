from datetime import date

from rules.tests.conftest import APRON2, SEASON, check, codes, league, leg, p, team

M = 1_000_000


def _aggregate(payroll_a: int, cash: int = 0):
    a1, a2, b = p("AAA", 10 * M), p("AAA", 10 * M), p("BBB", 18 * M)
    lg = league(team("AAA", payroll_a, a1, a2), team("BBB", 150 * M, b))
    return check(lg, leg("AAA", "BBB", [a1, a2], cash=cash), leg("BBB", "AAA", [b]))


def test_second_apron_team_cannot_aggregate():
    v = _aggregate(235 * M)
    assert "SECOND_APRON_AGGREGATION" in codes(v)


def test_aggregation_allowed_below_second_apron_but_hard_caps():
    v = _aggregate(195 * M)
    assert v.valid, v.explain()
    aaa = next(t for t in v.teams if t.team == "AAA")
    assert aaa.hard_cap == "second_apron"


def test_second_apron_team_cannot_send_cash():
    x, y = p("AAA", 10 * M), p("BBB", 9 * M)
    lg = league(team("AAA", 230 * M, x), team("BBB", 150 * M, y))
    v = check(lg, leg("AAA", "BBB", [x], cash=1 * M), leg("BBB", "AAA", [y]))
    assert codes(v) == ["SECOND_APRON_CASH"]


def test_cash_below_second_apron_allowed_and_hard_caps():
    x, y = p("AAA", 10 * M), p("BBB", 9 * M)
    lg = league(team("AAA", 190 * M, x), team("BBB", 150 * M, y))
    v = check(lg, leg("AAA", "BBB", [x], cash=1 * M), leg("BBB", "AAA", [y]))
    assert v.valid
    assert next(t for t in v.teams if t.team == "AAA").hard_cap == "second_apron"


def test_taking_back_more_salary_hard_caps_at_first_apron():
    x, y = p("AAA", 10 * M), p("BBB", 15 * M)
    lg = league(team("AAA", 180 * M, x), team("BBB", 150 * M, y))
    v = check(lg, leg("AAA", "BBB", [x]), leg("BBB", "AAA", [y]))
    assert next(t for t in v.teams if t.team == "AAA").hard_cap == "first_apron"


def test_sending_two_players_for_picks_is_not_aggregation():
    a1, a2 = p("AAA", 10 * M), p("AAA", 10 * M)
    lg = league(team("AAA", 235 * M, a1, a2), team("BBB", 120 * M))
    v = check(lg, leg("AAA", "BBB", [a1, a2]), leg("BBB", "AAA", picks=["2029-2-BBB"]))
    assert "SECOND_APRON_AGGREGATION" not in codes(v)


def test_shedding_below_second_apron_lifts_restriction():
    a1, a2, b = p("AAA", 15 * M), p("AAA", 15 * M), p("BBB", 5 * M)
    lg = league(team("AAA", APRON2 + 10 * M, a1, a2), team("BBB", 120 * M, b))
    v = check(lg, leg("AAA", "BBB", [a1, a2]), leg("BBB", "AAA", [b]))
    assert "SECOND_APRON_AGGREGATION" not in codes(v)


def test_cash_limit_exact_is_valid():
    lg = league(team("AAA", 150 * M), team("BBB", 150 * M))
    v = check(
        lg, leg("AAA", "BBB", cash=SEASON.trade.cash_limit), leg("BBB", "AAA", picks=["2030-2-BBB"])
    )
    assert v.valid


def test_cash_over_limit_fails_for_both_sides():
    lg = league(team("AAA", 150 * M), team("BBB", 150 * M))
    v = check(
        lg,
        leg("AAA", "BBB", cash=SEASON.trade.cash_limit + 1),
        leg("BBB", "AAA", picks=["2030-2-BBB"]),
    )
    assert codes(v) == ["CASH_LIMIT", "CASH_LIMIT"]
    assert {x.details["direction"] for x in v.violations} == {"send", "receive"}


def test_negative_cash_rejected_by_model():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        leg("AAA", "BBB", cash=-1)


def _pick_swap(day):
    lg = league(team("AAA", 150 * M), team("BBB", 150 * M))
    return check(
        lg,
        leg("AAA", "BBB", picks=["2030-2-AAA"]),
        leg("BBB", "AAA", picks=["2031-2-BBB"]),
        day=day,
    )


def test_trade_on_deadline_day_allowed():
    assert _pick_swap(SEASON.calendar.trade_deadline).valid


def test_trade_after_deadline_rejected():
    assert codes(_pick_swap(date(2027, 2, 12))) == ["TRADE_DEADLINE_PASSED"]


def test_trade_outside_league_year_rejected():
    assert codes(_pick_swap(date(2026, 6, 30))) == ["OUTSIDE_LEAGUE_YEAR"]
    assert codes(_pick_swap(date(2027, 7, 1))) == ["OUTSIDE_LEAGUE_YEAR"]


def test_offseason_trade_allowed():
    assert _pick_swap(date(2026, 7, 10)).valid
