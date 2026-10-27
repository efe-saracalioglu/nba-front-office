from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import yaml

from agents import tracing
from agents.deps import Deps
from agents.graph import build
from agents.llm import LLM, cost_report
from data.config import ROOT

RESULTS = ROOT / "evals" / "results"
NEWS_FIXTURES = ROOT / "evals" / "nba_bench" / "news_fixtures"
os.environ.setdefault("FRONT_OFFICE_NEWS_FIXTURES", str(NEWS_FIXTURES))
CONFIGS = ROOT / "evals" / "configs.yaml"
ROLES = ("router", "gm", "stats", "scout", "cap", "devils_advocate", "memo")


@cache
def configs() -> dict:
    return yaml.safe_load(CONFIGS.read_text(encoding="utf-8"))


def make_deps(config_name: str) -> Deps:
    cfg = configs()[config_name]
    overrides = {r: cfg["all_roles"] for r in ROLES} if cfg.get("all_roles") else {}
    overrides |= cfg.get("roles", {})
    return Deps(
        llm=LLM(overrides=overrides),
        devils_advocate=cfg.get("devils_advocate", True),
        sql_self_correction=cfg.get("sql_self_correction", True),
    )


def run_graph(
    deps: Deps, request: str, team: str | None, trade_date: str, tags: list[str], session: str
) -> dict:
    graph = build(deps, checkpoint_path=None, human_in_the_loop=False)
    models = {r: deps.llm.model_for(r) for r in ROLES}
    start = time.perf_counter()
    with tracing.run_trace("nba-bench", session, tags, models, request) as root:
        try:
            state = graph.invoke({"request": request, "team": team, "trade_date": trade_date})
            error = state.get("error")
        except Exception as e:
            state, error = {}, f"{type(e).__name__}: {e}"
        trace_id = tracing.current_trace_id()
        root.update(output=state.get("memo") or state.get("answer") or error)
    usage = deps.llm.usage()
    return {
        "state": state,
        "error": error,
        "trace_id": trace_id,
        "seconds": round(time.perf_counter() - start, 1),
        "cost": cost_report(usage)["total"],
        "tool_calls": len(deps.tools.calls),
    }


class TransientError(RuntimeError):
    pass


TRANSIENT_MARKERS = (
    "429",
    "502",
    "503",
    "504",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "RemoteProtocolError",
    "rate limit",
)


def is_transient(error: str | None) -> bool:
    return bool(error) and any(m.lower() in error.lower() for m in TRANSIENT_MARKERS)


def results_path(suite: str, config_name: str) -> Path:
    return RESULTS / suite / f"{config_name}.jsonl"


def resume(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def run_suite(
    suite: str, config_name: str, items: Iterable[dict], run_one: Callable[[dict, str], dict]
) -> list[dict]:
    path = results_path(suite, config_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = resume(path)
    items = list(items)
    with path.open("a", encoding="utf-8") as f:
        for i, item in enumerate(items, 1):
            if item["id"] in done:
                continue
            row = {
                "id": item["id"],
                "config": config_name,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            row |= run_one(item, config_name)
            if is_transient(row.get("error")):
                raise TransientError(f"{item['id']}: {row['error']}")
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            done[item["id"]] = row
            print(
                f"[{suite}/{config_name} {i}/{len(items)}] {item['id']}: {row.get('verdict', '')}",
                flush=True,
            )
    return [done[i["id"]] for i in items]


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
