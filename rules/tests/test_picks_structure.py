import pytest
from pydantic import ValidationError

from rules.models import PickAsset
from rules.tests.conftest import check, codes, league, leg, own_picks, p, team

M = 1_000_000


def _lg(picks=None):
    return league(team("AAA", 150 * M), team("BBB", 150 * M), picks=picks)


def test_trading_two_consecutive_firsts_violates_stepien():
    v = check(_lg(), leg("AAA", "BBB", picks=["2027-1-AAA", "2028-1-AAA"]))
    assert codes(v) == ["STEPIEN"]
    assert v.violations[0].details["years"] == [2027, 2028]


def test_trading_alternate_firsts_is_fine():
    assert check(_lg(), leg("AAA", "BBB", picks=["2027-1-AAA", "2029-1-AAA", "2031-1-AAA"])).valid


def test_extra_first_covers_the_gap():
    picks = own_picks(["AAA", "BBB"])
    picks["2028-1-BBB"] = picks["2028-1-BBB"].model_copy(
        update={"owner": "AAA", "kind": "acquired"}
    )
    v = check(league(team("AAA", 150 * M), team("BBB", 150 * M), picks=picks),
              leg("AAA", "BBB", picks=["2027-1-AAA", "2028-1-AAA"]))  # fmt: skip
    assert v.valid


def test_existing_gap_blocks_trading_adjacent_first():
    picks = own_picks(["AAA", "BBB"])
    picks["2030-1-AAA"] = picks["2030-1-AAA"].model_copy(
        update={"owner": "BBB", "kind": "acquired"}
    )
    v = check(
        league(team("AAA", 150 * M), team("BBB", 150 * M), picks=picks),
        leg("AAA", "BBB", picks=["2031-1-AAA"]),
    )
    assert codes(v) == ["STEPIEN"]


def test_second_rounders_never_trigger_stepien():
    v = check(_lg(), leg("AAA", "BBB", picks=[f"{y}-2-AAA" for y in range(2027, 2034)]))
    assert v.valid


def test_swap_right_does_not_count_as_a_pick():
    picks = own_picks(["AAA", "BBB"])
    picks["2028-1-swap"] = PickAsset(
        asset_id="2028-1-swap", year=2028, round=1, owner="AAA", original="BBB", kind="swap_right"
    )
    v = check(league(team("AAA", 150 * M), team("BBB", 150 * M), picks=picks),
              leg("AAA", "BBB", picks=["2027-1-AAA", "2028-1-AAA"]))  # fmt: skip
    assert codes(v) == ["STEPIEN"]


def test_last_window_year_alone_is_fine():
    assert check(_lg(), leg("AAA", "BBB", picks=["2033-1-AAA"])).valid


def test_pick_outside_window():
    picks = own_picks(["AAA", "BBB"])
    picks["2034-1-AAA"] = PickAsset(
        asset_id="2034-1-AAA", year=2034, round=1, owner="AAA", original="AAA", kind="own"
    )
    v = check(
        league(team("AAA", 150 * M), team("BBB", 150 * M), picks=picks),
        leg("AAA", "BBB", picks=["2034-1-AAA"]),
    )
    assert "PICK_OUT_OF_WINDOW" in codes(v)


def test_cannot_trade_pick_you_do_not_own():
    v = check(_lg(), leg("AAA", "BBB", picks=["2029-1-BBB"]))
    assert codes(v) == ["PICK_NOT_OWNED"]


def test_unknown_pick():
    assert codes(check(_lg(), leg("AAA", "BBB", picks=["2029-1-ZZZ"]))) == ["PICK_NOT_OWNED"]


def test_unknown_team():
    v = check(_lg(), leg("AAA", "XYZ", picks=["2029-2-AAA"]))
    assert codes(v) == ["UNKNOWN_TEAM"] and v.teams == []


def test_player_not_on_team():
    b = p("BBB", 5 * M)
    lg = league(team("AAA", 150 * M), team("BBB", 150 * M, b))
    v = check(lg, leg("AAA", "BBB", [b]))
    assert codes(v) == ["PLAYER_NOT_ON_TEAM"]


def test_unknown_player():
    assert codes(check(_lg(), leg("AAA", "BBB", [999_999_999]))) == ["PLAYER_NOT_ON_TEAM"]


def test_same_player_twice():
    a, b = p("AAA", 5 * M), p("BBB", 5 * M)
    lg = league(team("AAA", 150 * M, a), team("BBB", 150 * M, b), team("CCC", 150 * M))
    v = check(lg, leg("AAA", "BBB", [a]), leg("AAA", "CCC", [a]), leg("BBB", "AAA", [b]))
    assert "DUPLICATE_ASSET" in codes(v)


def test_same_pick_twice():
    lg = league(team("AAA", 150 * M), team("BBB", 150 * M), team("CCC", 150 * M))
    v = check(lg, leg("AAA", "BBB", picks=["2029-2-AAA"]), leg("AAA", "CCC", picks=["2029-2-AAA"]))
    assert "DUPLICATE_ASSET" in codes(v)


def test_unknown_salary_blocks_validation():
    a, b = p("AAA", None), p("BBB", 5 * M)
    lg = league(team("AAA", 150 * M, a), team("BBB", 150 * M, b))
    assert "SALARY_UNKNOWN" in codes(check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b])))


def test_leg_to_same_team_rejected():
    with pytest.raises(ValidationError):
        leg("AAA", "AAA", picks=["2029-2-AAA"])


def test_three_team_trade():
    a, b, c = p("AAA", 20 * M), p("BBB", 18 * M), p("CCC", 22 * M)
    lg = league(team("AAA", 180 * M, a), team("BBB", 180 * M, b), team("CCC", 180 * M, c))
    v = check(
        lg,
        leg("AAA", "BBB", [a]),
        leg("BBB", "CCC", [b]),
        leg("CCC", "AAA", [c], picks=["2030-2-CCC"]),
    )
    assert v.valid, v.explain()
    assert {t.team: t.payroll_after for t in v.teams} == {
        "AAA": 182 * M,
        "BBB": 182 * M,
        "CCC": 176 * M,
    }


def test_traded_player_exception_created():
    a, b = p("AAA", 20 * M), p("BBB", 8 * M)
    lg = league(team("AAA", 190 * M, a), team("BBB", 150 * M, b))
    v = check(lg, leg("AAA", "BBB", [a]), leg("BBB", "AAA", [b]))
    assert next(t for t in v.teams if t.team == "AAA").traded_player_exception == 12 * M
    assert next(t for t in v.teams if t.team == "BBB").traded_player_exception == 0


def test_explain_lists_violations():
    v = check(_lg(), leg("AAA", "BBB", picks=["2027-1-AAA", "2028-1-AAA"]))
    text = v.explain()
    assert text.startswith("INVALID") and "[STEPIEN]" in text
