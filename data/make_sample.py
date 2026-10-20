"""Cut a small warehouse for CI, tests and the hosted demo.

    python -m data.make_sample [--seasons 3] [--game-log-seasons 1]

Keeps the last N seasons of stats, the last M seasons of game logs, and all
current-season tables (rosters, contracts, draft picks).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data import config, db

FULL_TABLES = ["teams", "players", "rosters", "contracts", "draft_picks", "injuries"]
SEASON_TABLES = ["player_season_stats", "player_season_advanced", "team_season_stats"]


def make_sample(src: Path, dst: Path, n_seasons: int, n_log_seasons: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    con = db.connect(dst)
    db.create_schema(con)
    con.execute(f"ATTACH '{src}' AS src (READ_ONLY)")
    seasons = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT season FROM src.player_season_stats ORDER BY season DESC"
        ).fetchall()
    ]
    keep = ", ".join(f"'{s}'" for s in seasons[:n_seasons])
    keep_logs = ", ".join(f"'{s}'" for s in seasons[:n_log_seasons])
    for t in FULL_TABLES:
        con.execute(f"INSERT INTO {t} SELECT * FROM src.{t}")
    for t in SEASON_TABLES:
        con.execute(f"INSERT INTO {t} SELECT * FROM src.{t} WHERE season IN ({keep})")
    if keep_logs:
        con.execute(f"INSERT INTO player_game_logs SELECT * FROM src.player_game_logs "
                    f"WHERE season IN ({keep_logs})")  # fmt: skip
    con.execute("DETACH src")
    con.execute("CHECKPOINT")
    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, default=config.default_db_path())
    parser.add_argument("--dst", type=Path, default=config.SAMPLE_DB)
    parser.add_argument("--seasons", type=int, default=3)
    parser.add_argument("--game-log-seasons", type=int, default=1)
    args = parser.parse_args()
    make_sample(args.src, args.dst, args.seasons, args.game_log_seasons)
    print(f"wrote {args.dst} ({args.dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
