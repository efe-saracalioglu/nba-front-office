import pytest

from rules.cli import parse_leg, render
from rules.tests.conftest import check, league, leg, p, team

M = 1_000_000


@pytest.fixture
def lg():
    return league(team("AAA", 150 * M, p("AAA", 5 * M, name="Nikola Jokić")), team("BBB", 150 * M))


def test_parse_leg_players_picks_and_cash(lg):
    parsed = parse_leg("AAA>BBB: nikola jokic , 2029-1-AAA, cash=1_000_000", lg)
    assert parsed.from_team == "AAA" and parsed.to_team == "BBB"
    assert parsed.picks == ["2029-1-AAA"] and parsed.cash == 1_000_000
    assert len(parsed.players) == 1


def test_parse_leg_unknown_player(lg):
    with pytest.raises(ValueError, match="no player named"):
        parse_leg("AAA>BBB:Nobody", lg)


def test_parse_leg_bad_format(lg):
    with pytest.raises(ValueError, match="bad leg"):
        parse_leg("AAA to BBB", lg)


def test_render_includes_payrolls(lg):
    v = check(lg, leg("AAA", "BBB", picks=["2029-2-AAA"]))
    text = render(v)
    assert text.startswith("VALID") and "AAA: payroll $150.0M" in text
