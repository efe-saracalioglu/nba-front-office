from __future__ import annotations

import json

from agents.deps import Deps, prompt
from agents.schemas import Answer, SqlStep
from agents.toolbox import ToolCallError

REQUIRED = ["player_name", "team", "position", "age", "projected_ws", "salary"]
MAX_ATTEMPTS = 3

FALLBACK_SQL = """
SELECT p.player_name, t.abbreviation AS team, p.position, j.age_next AS age, j.projected_ws, j.salary
FROM player_projections j JOIN players p USING (player_id) JOIN teams t ON t.team_id = j.team_id
WHERE t.abbreviation <> '{team}' AND j.salary IS NOT NULL AND p.position IN ({positions})
  AND j.age_next <= {max_age} AND j.projected_ws >= {min_ws} AND j.salary <= {max_salary}
ORDER BY j.projected_ws DESC LIMIT 15
"""


def _context(deps: Deps, tables: list[str] | None) -> str:
    if tables:
        schema = json.dumps({t: deps.tools.call("describe_schema", table=t) for t in tables})
    else:
        schema = json.dumps(deps.tools.call("describe_schema"))
    examples = deps.tools.read("frontoffice://sql-examples")
    return f"Schema:\n{schema}\n\nWorked examples:\n{examples}"


def _rows_to_dicts(result: dict) -> list[dict]:
    return [dict(zip(result["columns"], row, strict=True)) for row in result["rows"]]


def _check(result: dict) -> str | None:
    missing = [c for c in REQUIRED if c not in result["columns"]]
    if missing:
        return f"The query must return columns {REQUIRED}; missing {missing}."
    if not result["rows"]:
        return "The query returned no rows; the filters are probably too strict or a join is wrong."
    return None


def sql_loop(
    deps: Deps,
    task: str,
    check=_check,
    tables: list[str] | None = None,
    system_prompt: str = "stats_analyst",
) -> tuple[list[dict], list[dict]]:
    system = prompt(system_prompt)
    context = _context(deps, tables)
    attempts, feedback = [], ""
    max_attempts = MAX_ATTEMPTS if deps.sql_self_correction else 1
    for i in range(max_attempts):
        user = f"{task}\n\n{context}"
        if feedback:
            user += f"\n\nPrevious SQL:\n{attempts[-1]['sql']}\nProblem: {feedback}"
        step = deps.llm.structured("stats", system, user, SqlStep)
        try:
            result = deps.tools.call("run_sql", query=step.sql)
            feedback = check(result) or ""
        except ToolCallError as e:
            result, feedback = None, str(e)
        attempts.append(
            {"attempt": i + 1, "sql": step.sql, "ok": not feedback, "problem": feedback or None}
        )
        if not feedback:
            return _rows_to_dicts(result), attempts
    return [], attempts


def find_candidates(deps: Deps, goal: dict) -> tuple[list[dict], list[dict]]:
    task = (
        f"Brief: {json.dumps(goal)}\n"
        f"Find trade targets for {goal['team']}: positions {goal['positions']}, age at most {goal['max_age']}, "
        f"projected_ws at least {goal['min_projected_ws']}"
        + (f", salary at most {goal['max_salary']}." if goal.get("max_salary") else ".")
    )
    rows, attempts = sql_loop(deps, task, tables=["player_projections", "players", "teams"])
    if not rows:
        sql = FALLBACK_SQL.format(
            team=goal["team"],
            positions=", ".join(f"'{p}'" for p in goal["positions"]),
            max_age=goal["max_age"],
            min_ws=goal["min_projected_ws"],
            max_salary=goal.get("max_salary") or 10**10,
        )
        rows = _rows_to_dicts(deps.tools.call("run_sql", query=sql))
        attempts.append({"attempt": "fallback", "sql": sql, "ok": bool(rows), "problem": None})
    own = goal["team"].upper()
    seen, out = set(), []
    for r in rows:
        if r["team"] == own or r["player_name"] in seen or not r.get("salary"):
            continue
        seen.add(r["player_name"])
        out.append(r)
    return out, attempts


def answer_question(deps: Deps, question: str) -> tuple[str, list[dict]]:
    task = f"Answer this question with one SELECT: {question}\nReturn whatever columns answer it; LIMIT 25."
    rows, attempts = sql_loop(
        deps,
        task,
        check=lambda r: None if r["rows"] else "The query returned no rows.",
        system_prompt="stats_question",
    )
    data = json.dumps(
        {"question": question, "rows": rows[:25], "sql": attempts[-1]["sql"] if attempts else None}
    )
    ans = deps.llm.structured("stats", prompt("answer"), data, Answer)
    return ans.answer, attempts
