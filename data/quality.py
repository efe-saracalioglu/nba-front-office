from __future__ import annotations

import duckdb

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
        "draft picks: every team has one own-pick asset per draft and round",
        """SELECT count(*) FROM (
             SELECT original_team_id, year, round, count(*) n FROM draft_picks
             WHERE kind IN ('own', 'acquired') AND original_team_id IS NOT NULL
             GROUP BY ALL HAVING n <> 1)""",
        lambda n: n == 0,
    ),
    (
        "draft picks loaded (30 teams x 7 drafts x 2 rounds)",
        "SELECT count(*) FROM draft_picks WHERE kind IN ('own', 'acquired')",
        lambda n: n == 420,
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


PBP_CHECKS = [
    (
        "play-by-play points match box scores (>=99.5% of player-games)",
        """WITH p AS (SELECT game_id, player_id, sum(points) pts FROM pbp_events GROUP BY ALL)
           SELECT avg(CASE WHEN coalesce(p.pts, 0) = g.pts THEN 1 ELSE 0 END)
           FROM player_game_logs g LEFT JOIN p USING (game_id, player_id)
           WHERE g.game_id IN (SELECT DISTINCT game_id FROM pbp_events)""",
        lambda r: r is not None and r >= 0.995,
    ),
    (
        "every box-score game has play-by-play (up to the last date covered)",
        """WITH g AS (SELECT DISTINCT game_id, season, game_date FROM player_game_logs),
                covered AS (SELECT season, max(game_date) last_day FROM g
                            WHERE game_id IN (SELECT game_id FROM pbp_events) GROUP BY 1)
           SELECT count(*) FROM g JOIN covered USING (season)
           WHERE g.game_date <= covered.last_day
             AND g.game_id NOT IN (SELECT DISTINCT game_id FROM pbp_events)""",
        lambda n: n == 0,
    ),
]


def _has_rows(con, table: str) -> bool:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0


def run_checks(con: duckdb.DuckDBPyConnection) -> list[str]:
    checks = list(CHECKS)
    if _has_rows(con, "player_game_logs"):
        checks.append(GAME_LOG_CHECK)
        if _has_rows(con, "pbp_events"):
            checks.extend(PBP_CHECKS)
    failures = []
    for desc, sql, ok in checks:
        value = con.execute(sql).fetchone()[0]
        if not ok(value):
            failures.append(f"{desc} (got {value})")
    return failures
