import pytest

from agents.deps import Deps
from agents.tests.test_agents import ScriptedLLM
from agents.toolbox import ToolBox
from app import session
from data import config

pytestmark = pytest.mark.skipif(not config.SAMPLE_DB.exists(), reason="sample warehouse missing")


@pytest.fixture
def sample_db(monkeypatch):
    monkeypatch.setenv("FRONT_OFFICE_DB", str(config.SAMPLE_DB))
    from mcp_server import warehouse

    warehouse.league.cache_clear()
    yield
    warehouse.league.cache_clear()


def graph(tmp_path, **kw):
    deps = Deps(llm=ScriptedLLM(**kw), tools=ToolBox())
    return session.make_graph(True, deps=deps, checkpoint_path=tmp_path / "ck.sqlite")


def test_run_pauses_for_approval_then_writes_memo(sample_db, tmp_path):
    run = session.Run(request="find us a center", team="BOS")
    events = list(session.start(run, graph(tmp_path), "2026-12-20"))
    assert events[0].startswith("router:")
    assert run.pending is not None and run.pending["proposals"]
    assert not run.finished
    keep = session.default_selection(run.pending)
    assert keep == [p["id"] for p in run.pending["proposals"]]

    list(session.resume(run, graph(tmp_path), keep[:1], "only the first"))
    assert run.finished
    assert run.state["approval"] == {"approved": keep[:1], "notes": "only the first"}
    assert run.state["memo"].startswith("## Recommendation")
    assert session.costs(run.state)["total"]["calls"] > 0


def test_thread_can_be_reloaded_at_the_approval_step(sample_db, tmp_path):
    run = session.Run(request="find us a center", team="BOS")
    list(session.start(run, graph(tmp_path), "2026-12-20"))
    loaded = session.load(run.thread, graph(tmp_path))
    assert loaded.request == run.request
    assert loaded.pending == run.pending
    assert session.load("missing", graph(tmp_path)) is None


def test_dropped_proposals_are_not_preselected():
    pending = {"proposals": [{"id": "P1"}, {"id": "P2"}],
               "critiques": [{"proposal_id": "P2", "verdict": "drop"}]}  # fmt: skip
    assert session.default_selection(pending) == ["P1"]


def test_page_renders_without_a_run(sample_db):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(config.ROOT / "app" / "streamlit_app.py"), default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value.endswith("Front Office")
    assert any(m.label == "Payroll" for m in at.metric)


def test_approval_and_result_views_render(sample_db, tmp_path):
    from streamlit.testing.v1 import AppTest

    run = session.Run(request="find us a center", team="BOS")
    list(session.start(run, graph(tmp_path), "2026-12-20"))
    at = AppTest.from_file(str(config.ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    at.session_state["run"] = run
    at.run()
    assert not at.exception
    assert "Proposals awaiting your approval" in [s.value for s in at.subheader]
    assert len(at.checkbox) == len(run.pending["proposals"])

    list(session.resume(run, graph(tmp_path), ["P1"], None))
    at.session_state["run"] = run
    at.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Memo", "Proposals", "Agent steps", "Cost & latency"]


def test_demo_limit_blocks_new_requests(sample_db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FRONT_OFFICE_DEMO_LIMIT", "2")
    at = AppTest.from_file(str(config.ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    at.session_state["requests"] = 2
    at.run()
    assert not at.exception
    assert "2 requests per session" in at.info[0].value
    assert not at.text_area
