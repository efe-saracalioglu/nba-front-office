"""Warehouse data-quality checks. Each check returns a message when it fails."""

from __future__ import annotations

import duckdb

# (description, SQL returning a single number, predicate on that number)
CHECKS: list[tuple[str, str, callable]] = [
    ("30 teams", "SELECT count(*) FROM teams", lambda n: n == 30),
    (
        "every season has 400+ players",
        """SELECT coalesce(min(n), 0)
           FROM (SELECT count(*) n FROM player_season_stats GROUP BY season)""",
        lambda n: n >= 400,
    ),
    (
        "every season has 30 teams with stats",
        """SELECT coalesce(min(n), 0)
           FROM (SELECT count(*) n FROM team_season_stats GROUP BY season)""",
        lambda n: n == 30,
    ),
    (
        ">=98% of minutes have advanced (bbref) metrics",
        """SELECT sum(CASE WHEN a.player_id IS NOT NULL THEN s.min END) / sum(s.min)
           FROM player_season_stats s
           LEFT JOIN player_season_advanced a USING (player_id, season)""",
        lambda r: r is not None and r >= 0.98,
    ),
    (
        "bbref games match nba games for matched rows (>=97%)",
        """SELECT avg(CASE WHEN a.g = s.gp THEN 1 ELSE 0 END)
           FROM player_season_stats s JOIN player_season_advanced a USING (player_id, season)""",
        lambda r: r is not None and r >= 0.97,
    ),
    (
        "percentages are fractions",
        """SELECT count(*) FROM player_season_advanced
           WHERE usg_pct > 1 OR ts_pct > 1.5 OR ast_pct > 1""",
        lambda n: n == 0,
    ),
    (
        "rosters cover 30 teams",
        "SELECT count(DISTINCT team_id) FROM rosters",
        lambda n: n == 30,
    ),
    (
        ">=95% of current-season contracts map to an NBA.com player",
        """SELECT avg(CASE WHEN player_id IS NOT NULL THEN 1 ELSE 0 END) FROM contracts
           WHERE season = (SELECT min(season) FROM contracts)""",
        lambda r: r is not None and r >= 0.95,
    ),
    (
        "current-season contracts map to a team",
        """SELECT count(*) FROM contracts
           WHERE team_id IS NULL AND season = (SELECT min(season) FROM contracts)""",
        lambda n: n == 0,
    ),
    (
        "no negative salaries",
        "SELECT count(*) FROM contracts WHERE salary <= 0",
        lambda n: n == 0,
    ),
]

GAME_LOG_CHECK = (
    "game logs sum to season totals (points, >=99% of player-seasons)",
    """SELECT avg(CASE WHEN g.pts = s.pts THEN 1 ELSE 0 END)
       FROM player_season_stats s
       JOIN (SELECT player_id, season, sum(pts) pts FROM player_game_logs GROUP BY ALL) g
       USING (player_id, season)""",
    lambda r: r is not None and r >= 0.99,
)


def run_checks(con: duckdb.DuckDBPyConnection) -> list[str]:
    checks = list(CHECKS)
    if con.execute("SELECT count(*) FROM player_game_logs").fetchone()[0]:
        checks.append(GAME_LOG_CHECK)
    failures = []
    for desc, sql, ok in checks:
        value = con.execute(sql).fetchone()[0]
        if not ok(value):
            failures.append(f"{desc} (got {value})")
    return failures
