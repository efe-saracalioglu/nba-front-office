"""NBA.com stats via nba_api, cached to parquet under data/raw/nba_api/.

Every fetch is cached by (endpoint, args) so re-running the ETL never re-hits the API
unless `refresh=True`. Completed seasons never change, so the cache is the source of truth.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import pandas as pd
from nba_api.stats.endpoints import (
    commonteamroster,
    leaguedashplayerbiostats,
    leaguedashplayerstats,
    leaguedashteamstats,
    playergamelogs,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from data.config import RAW_DIR

log = logging.getLogger(__name__)

CACHE_DIR = RAW_DIR / "nba_api"
REQUEST_PAUSE_S = 0.8
TIMEOUT_S = 60


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30), reraise=True)
def _call(factory: Callable[[], object]) -> pd.DataFrame:
    df = factory().get_data_frames()[0]
    time.sleep(REQUEST_PAUSE_S)
    return df


def _cached(key: str, factory: Callable[[], object], refresh: bool) -> pd.DataFrame:
    path = CACHE_DIR / f"{key}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    log.info("nba_api fetch %s", key)
    df = _call(factory)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def player_stats(season: str, measure: str, refresh: bool = False) -> pd.DataFrame:
    """measure: 'Base' (totals) or 'Advanced'."""
    return _cached(
        f"player_stats_{measure.lower()}_{season}",
        lambda: leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            measure_type_detailed_defense=measure,
            per_mode_detailed="Totals",
            timeout=TIMEOUT_S,
        ),
        refresh,
    )


def player_bio(season: str, refresh: bool = False) -> pd.DataFrame:
    return _cached(
        f"player_bio_{season}",
        lambda: leaguedashplayerbiostats.LeagueDashPlayerBioStats(season=season, timeout=TIMEOUT_S),
        refresh,
    )


def game_logs(season: str, refresh: bool = False) -> pd.DataFrame:
    return _cached(
        f"game_logs_regular_{season}",
        lambda: playergamelogs.PlayerGameLogs(
            season_nullable=season, season_type_nullable="Regular Season", timeout=TIMEOUT_S
        ),
        refresh,
    )


def team_stats(season: str, measure: str, refresh: bool = False) -> pd.DataFrame:
    return _cached(
        f"team_stats_{measure.lower()}_{season}",
        lambda: leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense=measure,
            per_mode_detailed="PerGame",
            timeout=TIMEOUT_S,
        ),
        refresh,
    )


def team_roster(team_id: int, season: str, refresh: bool = False) -> pd.DataFrame:
    return _cached(
        f"roster_{team_id}_{season}",
        lambda: commonteamroster.CommonTeamRoster(
            team_id=team_id, season=season, timeout=TIMEOUT_S
        ),
        refresh,
    )
