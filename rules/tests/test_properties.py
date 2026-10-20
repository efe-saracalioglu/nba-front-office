from hypothesis import given, settings
from hypothesis import strategies as st

from rules.cba.salary_matching import expanded_matching_limit, max_incoming_salary
from rules.context import TeamFlow
from rules.tests.conftest import APRON1, CAP, SEASON, check, codes, league, leg, p, team

M = 1_000_000
salaries = st.integers(min_value=1_200_000, max_value=60 * M)
payrolls = st.integers(min_value=120 * M, max_value=240 * M)
MATCHING = {"SALARY_MATCHING", "SALARY_MATCHING_APRON", "ABSORB_WITHOUT_ROOM"}


@given(st.integers(min_value=0, max_value=80 * M))
def test_expanded_limit_never_below_outgoing_plus_cushion(out):
    assert expanded_matching_limit(out, SEASON) >= out + SEASON.trade.matching_cushion


@given(st.integers(min_value=0, max_value=80 * M), st.integers(min_value=1, max_value=5 * M))
def test_expanded_limit_is_monotonic(out, delta):
    assert expanded_matching_limit(out + delta, SEASON) >= expanded_matching_limit(out, SEASON)


@settings(max_examples=150, deadline=None)
@given(payrolls, salaries, payrolls)
def test_equal_salary_swap_never_breaks_matching(payroll_a, salary, payroll_b):
    a, b = p("AAA", salary), p("BBB", salary)
    lg = league(team("AAA", payroll_a + salary, a), team("BBB", payroll_b + salary, b))
    v = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
    assert not MATCHING & set(codes(v))


@settings(max_examples=150, deadline=None)
@given(payrolls, salaries)
def test_max_incoming_is_the_exact_boundary(payroll, out):
    a = p("AAA", out)
    state = team("AAA", payroll, a)
    limit = max_incoming_salary(TeamFlow(team="AAA", state=state, out_players=[a]), SEASON)
    for incoming, should_pass in ((limit, True), (limit + 1, False)):
        b = p("BBB", incoming)
        lg = league(team("AAA", payroll, a), team("BBB", 100 * M, b, standard=13))
        v = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
        aaa_matching = [x for x in v.violations if x.team == "AAA" and x.code in MATCHING]
        assert (not aaa_matching) == should_pass


@settings(max_examples=100, deadline=None)
@given(payrolls, salaries, salaries)
def test_verdict_does_not_depend_on_leg_order(payroll, s1, s2):
    a, b = p("AAA", s1), p("BBB", s2)
    lg = league(team("AAA", payroll, a), team("BBB", payroll, b))
    forward = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
    backward = check(lg, leg("BBB", "AAA", [b]), leg("AAA", "BBB", [a]))
    assert forward.valid == backward.valid
    assert codes(forward) == codes(backward)


@settings(max_examples=100, deadline=None)
@given(payrolls, salaries, salaries)
def test_adding_a_second_round_pick_never_changes_salary_verdict(payroll, s1, s2):
    a, b = p("AAA", s1), p("BBB", s2)
    lg = league(team("AAA", payroll, a), team("BBB", payroll, b))
    base = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
    sweetened = check(lg, leg("AAA", "BBB", [a], picks=["2031-2-AAA"]), leg("BBB", "AAA", [b]))
    assert MATCHING & set(codes(base)) == MATCHING & set(codes(sweetened))


@settings(max_examples=100, deadline=None)
@given(
    st.integers(min_value=100 * M, max_value=CAP - 1), st.integers(min_value=1, max_value=60 * M)
)
def test_under_cap_absorption_valid_iff_it_fits(payroll, incoming):
    b = p("BBB", incoming)
    lg = league(team("AAA", payroll), team("BBB", 200 * M, b))
    v = check(lg, leg("BBB", "AAA", [b]))
    fits = payroll + incoming <= CAP or incoming <= SEASON.trade.matching_cushion
    assert (not MATCHING & set(codes(v))) == fits


@settings(max_examples=100, deadline=None)
@given(st.integers(min_value=APRON1 + 1, max_value=260 * M), salaries, salaries)
def test_apron_team_never_takes_back_more(payroll, out, incoming):
    a, b = p("AAA", out), p("BBB", incoming)
    lg = league(team("AAA", payroll, a), team("BBB", 150 * M, b))
    v = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
    apron_violation = any(x.team == "AAA" and x.code in MATCHING for x in v.violations)
    if payroll - out + incoming > APRON1:
        assert apron_violation == (incoming > out)
