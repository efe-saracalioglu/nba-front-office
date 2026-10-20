from __future__ import annotations

from pathlib import Path

import duckdb

from data.config import SCHEMA_SQL, default_db_path


def connect(path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(path) if path else default_db_path()
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def replace_rows(
    con: duckdb.DuckDBPyConnection, table: str, df, where: str | None = None, source: str = ""
) -> int:
    """Idempotent load: delete the slice described by `where` (or the whole table), then insert.

    Columns are matched by name, so `df` may hold them in any order but must not hold extras.
    """
    con.register("_incoming", df)
    try:
        con.execute("BEGIN")
        con.execute(f"DELETE FROM {table}" + (f" WHERE {where}" if where else ""))
        cols = ", ".join(df.columns)
        con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
        con.execute(
            "INSERT INTO etl_runs (table_name, rows_loaded, source) VALUES (?, ?, ?)",
            [table, len(df), source],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_incoming")
    return len(df)
