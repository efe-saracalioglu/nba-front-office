from datetime import date

import duckdb
import pytest

from data import config
from rules.engine import validate_trade
from rules.models import Trade, TradeLeg
from rules.state import load_league

pytestmark = pytest.mark.skipif(not config.SAMPLE_DB.exists(), reason="sample warehouse missing")
DAY = date(2026, 11, 1)


@pytest.fixture(scope="module")
def lg():
    return load_league(config.SAMPLE_DB)


def _player(lg, name):
    found = lg.find_player(name)
    assert found is not None, name
    return found


def test_league_loads_every_team_and_pick(lg):
    assert len(lg.teams) == 30
    assert sum(a.kind in ("own", "acquired") for a in lg.picks.values()) == 420


def test_payroll_matches_contracts_table(lg):
    con = duckdb.connect(str(config.SAMPLE_DB), read_only=True)
    expected = dict(
        con.execute(
            """SELECT t.abbreviation, sum(c.salary) FROM contracts c JOIN teams t USING (team_id)
               WHERE c.season = '2026-27' AND NOT EXISTS (
                   SELECT 1 FROM rosters r WHERE r.is_two_way AND r.player_id = c.player_id
                     AND r.team_id = c.team_id) GROUP BY 1"""
        ).fetchall()
    )
    con.close()
    for abbr, team in lg.teams.items():
        assert team.payroll == expected[abbr], abbr


def test_jokic_for_curry_breaks_denver_apron_matching(lg):
    jok, cur = _player(lg, "Nikola Jokić"), _player(lg, "Stephen Curry")
    v = validate_trade(
        Trade(
            trade_date=DAY,
            legs=[
                TradeLeg(from_team=jok.team, to_team=cur.team, players=[jok.player_id]),
                TradeLeg(from_team=cur.team, to_team=jok.team, players=[cur.player_id]),
            ],
        ),
        lg,
    )
    assert not v.valid
    assert [x.code for x in v.violations] == ["SALARY_MATCHING_APRON"]
    assert v.violations[0].team == jok.team


def test_every_team_can_swap_a_pick_for_a_pick(lg):
    teams = sorted(lg.teams)
    for a, b in zip(teams, teams[1:], strict=False):
        give = next(x.asset_id for x in lg.picks.values() if x.owner == a and x.round == 2)
        take = next(x.asset_id for x in lg.picks.values() if x.owner == b and x.round == 2)
        v = validate_trade(
            Trade(
                trade_date=DAY,
                legs=[
                    TradeLeg(from_team=a, to_team=b, picks=[give]),
                    TradeLeg(from_team=b, to_team=a, picks=[take]),
                ],
            ),
            lg,
        )
        assert v.valid, (a, b, v.explain())


def test_waived_player_salary_counted_once(lg):
    total = sum(t.payroll for t in lg.teams.values())
    con = duckdb.connect(str(config.SAMPLE_DB), read_only=True)
    contracts = con.execute(
        """SELECT sum(salary) FROM contracts c WHERE season = '2026-27' AND NOT EXISTS (
               SELECT 1 FROM rosters r WHERE r.is_two_way AND r.player_id = c.player_id
                 AND r.team_id = c.team_id)"""
    ).fetchone()[0]
    con.close()
    assert total == contracts
