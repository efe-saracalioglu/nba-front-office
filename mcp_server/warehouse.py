from __future__ import annotations

import os
import re
import threading
from functools import cache
from pathlib import Path

import duckdb

from data.config import DATA_DIR, SAMPLE_DB, SCHEMA_SQL
from rules.state import LeagueState, load_league

MAX_ROWS = 200
TIMEOUT_S = 15.0


class QueryError(ValueError):
    pass


def db_path() -> Path:
    env = os.environ.get("FRONT_OFFICE_DB")
    if env:
        return Path(env)
    full = DATA_DIR / "warehouse.duckdb"
    return full if full.exists() else SAMPLE_DB


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(
        str(path or db_path()), read_only=True, config={"enable_external_access": False}
    )
    if not con.execute("SELECT current_setting('lock_configuration')").fetchone()[0]:
        con.execute("SET lock_configuration = true")
    return con


@cache
def league(path: str | None = None) -> LeagueState:
    con = connect(Path(path) if path else None)
    try:
        return load_league(con=con)
    finally:
        con.close()


def _only_selects(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as e:
        raise QueryError(f"SQL could not be parsed: {e}") from e
    if len(statements) != 1:
        raise QueryError("Send exactly one SQL statement.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise QueryError(f"Only SELECT queries are allowed (got {statements[0].type.name}).")


def run_query(
    con: duckdb.DuckDBPyConnection, sql: str, max_rows: int = MAX_ROWS, timeout: float = TIMEOUT_S
) -> dict:
    sql = sql.strip().rstrip(";")
    _only_selects(con, sql)
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
    except duckdb.InterruptException as e:
        raise QueryError(
            f"Query took longer than {timeout:.0f}s and was cancelled; add filters or aggregate."
        ) from e
    except duckdb.Error as e:
        raise QueryError(str(e).splitlines()[0]) from e
    finally:
        timer.cancel()
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "columns": columns,
        "rows": [[_jsonable(v) for v in r] for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def _jsonable(v):
    if v is None or isinstance(v, bool | int | float | str):
        return v
    return str(v)


_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", re.S)
_COLUMN = re.compile(r"^\s*(\w+)\s+([A-Z]+)")


@cache
def schema_doc() -> dict[str, dict]:
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    out = {}
    for m in _TABLE.finditer(text):
        name, body = m.groups()
        preface = text[: m.start()].rstrip().split("\n\n")[-1]
        about = " ".join(
            line.lstrip("- ").strip() for line in preface.splitlines() if line.startswith("--")
        )
        columns = []
        for line in body.splitlines():
            code, _, note = line.partition("--")
            if code.strip().startswith("PRIMARY KEY"):
                continue
            for part in code.split(","):
                c = _COLUMN.match(part)
                if c:
                    columns.append({"name": c[1], "type": c[2], "note": note.strip()})
        out[name] = {"about": about, "columns": columns}
    return out
