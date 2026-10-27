import pytest

from agents import cap_analyst, stats_analyst
from agents.deps import Deps
from agents.graph import build
from agents.llm import LLM, Call, cost_report
from agents.schemas import Answer, Critique, Critiques, Route, ScoutReport, SqlStep, TeamGoal
from agents.toolbox import ToolBox
from data import config

pytestmark = pytest.mark.skipif(not config.SAMPLE_DB.exists(), reason="sample warehouse missing")

GOAL = {
    "team": "BOS",
    "need": "rim-protecting center",
    "positions": ["C"],
    "min_projected_ws": 4.0,
    "max_age": 32,
    "stay_below": "second_apron",
    "protected_picks": ["2029"],
    "untouchable_players": ["Jayson Tatum"],
    "timeline": "win_now",
}
GOOD_SQL = (
    "SELECT p.player_name, t.abbreviation AS team, p.position, j.age_next AS age, j.projected_ws, j.salary "
    "FROM player_projections j JOIN players p USING (player_id) JOIN teams t ON t.team_id = j.team_id "
    "WHERE p.position = 'C' AND j.salary IS NOT NULL ORDER BY j.projected_ws DESC LIMIT 15"
)


class ScriptedLLM(LLM):
    def __init__(self, sql=None, verdict="keep", route="trade_search"):
        super().__init__()
        self.sql = list(sql or [GOOD_SQL])
        self.verdict = verdict
        self.route_name = route

    def _log(self, role):
        self.calls.append(Call(role, "scripted", 10, 5, 0.0, 1, True))

    def structured(self, role, system, user, schema, retries=2):
        self._log(role)
        if schema is Route:
            return Route(route=self.route_name, team="BOS", player="Victor Wembanyama")
        if schema is TeamGoal:
            return TeamGoal(**GOAL)
        if schema is SqlStep:
            return SqlStep(thought="", sql=self.sql.pop(0) if len(self.sql) > 1 else self.sql[0])
        if schema is ScoutReport:
            return ScoutReport(
                player="x",
                availability="healthy",
                risk="low",
                summary="ok",
                suspicious_content=False,
            )
        if schema is Critiques:
            ids = [
                line.split('"id": "')[1].split('"')[0]
                for line in user.split("{")
                if '"id": "P' in line
            ]
            return Critiques(
                critiques=[
                    Critique(
                        proposal_id=i,
                        verdict=self.verdict,
                        counterparty_would_accept=True,
                        concerns=[],
                        reasoning="scripted",
                    )
                    for i in ids
                ]
            )
        if schema is Answer:
            return Answer(answer="scripted answer")
        raise AssertionError(schema)

    def text(self, role, system, user):
        self._log(role)
        return "## Recommendation\nscripted memo"


@pytest.fixture
def deps(monkeypatch):
    monkeypatch.setenv("FRONT_OFFICE_DB", str(config.SAMPLE_DB))
    from mcp_server import warehouse

    warehouse.league.cache_clear()
    yield lambda **kw: Deps(llm=ScriptedLLM(**kw), tools=ToolBox())
    warehouse.league.cache_clear()


def test_tradable_picks_respect_protection():
    assets = {
        "owned": [
            {"asset_id": "2029-1-BOS", "year": 2029, "round": 1, "kind": "own"},
            {"asset_id": "2030-1-BOS", "year": 2030, "round": 1, "kind": "own"},
            {"asset_id": "2031-2-BOS", "year": 2031, "round": 2, "kind": "own"},
            {"asset_id": "2028-1-swap", "year": 2028, "round": 1, "kind": "swap_right"},
        ]
    }
    picks = cap_analyst.tradable_picks(assets, ["2029"])
    assert [p["asset_id"] for p in picks] == ["2031-2-BOS", "2030-1-BOS"]
    assert (
        cap_analyst.tradable_picks(assets, ["2030-1-BOS", "2029"])[-1]["asset_id"] == "2031-2-BOS"
    )


def test_sql_self_correction_recovers_from_an_error(deps):
    d = deps(sql=["SELECT nope FROM nowhere", GOOD_SQL])
    rows, attempts = stats_analyst.find_candidates(d, GOAL)
    assert [a["ok"] for a in attempts] == [False, True]
    assert (
        "nowhere" in attempts[0]["problem"].lower() or "catalog" in attempts[0]["problem"].lower()
    )
    assert rows and all(r["team"] != "BOS" for r in rows)


def test_without_self_correction_falls_back_to_template(deps):
    d = deps(sql=["SELECT nope FROM nowhere"])
    d.sql_self_correction = False
    rows, attempts = stats_analyst.find_candidates(d, GOAL)
    assert attempts[0]["ok"] is False and attempts[-1]["attempt"] == "fallback"
    assert rows


def test_proposals_are_legal_balanced_and_improve_us(deps):
    d = deps()
    rows, _ = stats_analyst.find_candidates(d, GOAL)
    proposals, outcomes = cap_analyst.propose(d, GOAL, rows, {}, "2026-12-20")
    assert set(outcomes) == {r["player_name"] for r in rows}
    tolerance = cap_analyst.market()["counterparty_tolerance"]
    for p in proposals:
        assert p["validation"]["valid"]
        assert p["value"]["ws_change_for_us"] > 0
        assert p["value"]["counterparty_value_change"] >= -tolerance
        assert not any(x["asset_id"].startswith("2029") for x in p["send_picks"])
        assert not any(x["name"] == "Jayson Tatum" for x in p["send_players"])
        ours = next(t for t in p["validation"]["teams"] if t["team"] == "BOS")
        assert ours["payroll_after"] < 221_686_000
        check = d.tools.call("validate_trade", legs=p["legs"], trade_date=p["trade_date"])
        assert check["valid"]


def test_full_graph_with_auto_approval(deps):
    d = deps()
    graph = build(d, checkpoint_path=None, human_in_the_loop=False)
    state = graph.invoke({"request": "find us a center", "team": "BOS", "trade_date": "2026-12-20"})
    assert state["route"] == "trade_search"
    assert state["memo"].startswith("## Recommendation")
    assert state["approval"]["approved"] == [p["id"] for p in state["proposals"]]
    roles = {u["role"] for u in state["usage"]}
    assert {"router", "gm", "stats", "scout", "devils_advocate", "memo"} <= roles
    assert any(t["tool"] == "validate_trade" for t in state["tool_calls"])


def test_dropped_proposals_are_not_auto_approved(deps):
    d = deps(verdict="drop")
    graph = build(d, checkpoint_path=None, human_in_the_loop=False)
    state = graph.invoke({"request": "find us a center", "team": "BOS", "trade_date": "2026-12-20"})
    assert state["revisions"] == 1
    assert state["approval"]["approved"] == []


def test_stats_question_route(deps):
    d = deps(route="stats_question", sql=["SELECT count(*) AS teams FROM teams"])
    graph = build(d, checkpoint_path=None, human_in_the_loop=False)
    state = graph.invoke({"request": "how many teams are there?"})
    assert state["answer"] == "scripted answer"
    assert "proposals" not in state


def test_cost_report_totals():
    usage = [
        {
            "role": "gm",
            "model": "ollama:gpt-oss:120b-cloud",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "seconds": 2.0,
        },
        {
            "role": "gm",
            "model": "ollama:gpt-oss:120b-cloud",
            "input_tokens": 0,
            "output_tokens": 1_000_000,
            "seconds": 3.0,
        },
    ]
    r = cost_report(usage)
    assert r["by_role"]["gm"]["calls"] == 2
    assert r["total"]["usd"] == pytest.approx(0.75)


def test_structured_output_unwraps_schema_echo():
    from pydantic import BaseModel

    from agents.llm import _validate

    class S(BaseModel):
        score: int

    assert _validate(S, {"properties": {"score": 4}}).score == 4
    assert _validate(S, {"score": 2}).score == 2


class FixedWS:
    def __init__(self, ws):
        self.values = ws

    def ws(self, name, team=None):
        return self.values[name]


def test_counterparty_wants_firsts_for_the_talent_it_loses():
    valuer = FixedWS({"Star": 7.0, "Role A": 1.5, "Role B": 1.0, "Starter": 5.5})
    send = [{"name": "Role A"}, {"name": "Role B"}]
    veteran = {"player_name": "Star", "team": "CLE", "age": 30}
    young = veteran | {"age": 23}
    assert cap_analyst.required_first_round_picks(valuer, veteran, send, "BOS") == 4
    assert cap_analyst.required_first_round_picks(valuer, young, send, "BOS") == 6
    even = [{"name": "Starter"}, {"name": "Role A"}]
    assert cap_analyst.required_first_round_picks(valuer, veteran, even, "BOS") == 0


def test_no_firsts_brief_keeps_first_round_picks_out(deps):
    d = deps()
    goal = GOAL | {"trade_first_round_picks": False}
    candidates, _ = stats_analyst.find_candidates(d, goal)
    props, _ = cap_analyst.propose(d, goal, candidates, {}, "2026-12-20")
    assert all(p["round"] != 1 for prop in props for p in prop["send_picks"])


def test_memo_fact_sheet_states_the_payroll_line():
    from agents.specialists import fact_sheet

    prop = {
        "id": "P1",
        "receive": {"name": "X", "salary": 10e6, "projected_ws": 4.0},
        "from_team": "OKC",
        "send_players": [],
        "send_picks": [],
        "value": {"ws_change_for_us": 1.0, "our_value_change": 0, "counterparty_value_change": 0},
        "validation": {
            "teams": [
                {
                    "team": "BOS",
                    "payroll_before": 200e6,
                    "payroll_after": 205e6,
                    "status_after": "over_tax",
                    "hard_cap": "first_apron",
                    "standard_roster_after": 14,
                }
            ]
        },
    }
    sheet = fact_sheet(prop, "BOS", {}, ("first_apron", 209_015_000))
    assert "below it, as the brief requires" in sheet["payroll_line"]
    assert "does not exceed the first apron" in sheet["hard_cap"]
    assert "NOT below" in fact_sheet(prop, "BOS", {}, ("luxury_tax", 200_428_000))["payroll_line"]
