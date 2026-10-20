"""Map Basketball-Reference player ids to NBA.com player ids.

Pass 1 matches on (normalized name, season). Pass 2 catches name variants
("Nic" vs "Nicolas Claxton") by matching games played and total minutes within a season,
which is effectively unique. A bbref_id that matches in any season is mapped for all seasons.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _SUFFIX.sub("", s)
    return " ".join(s.split())


def _unique_pairs(merged: pd.DataFrame) -> pd.DataFrame:
    """Keep only bbref_id <-> player_id pairs that are unambiguous in both directions."""
    pairs = merged[["bbref_id", "player_id"]].drop_duplicates()
    pairs = pairs[~pairs.bbref_id.duplicated(keep=False)]
    return pairs[~pairs.player_id.duplicated(keep=False)]


def build_crosswalk(bbref: pd.DataFrame, nba: pd.DataFrame) -> pd.DataFrame:
    """bbref: bbref_id, player_name, season, g, mp. nba: player_id, player_name, season, gp, min.

    Returns bbref_id, player_id, method.
    """
    b = bbref.assign(key=bbref.player_name.map(normalize_name))
    n = nba.assign(key=nba.player_name.map(normalize_name))

    by_name = _unique_pairs(b.merge(n[["key", "season", "player_id"]], on=["key", "season"]))
    by_name["method"] = "name"

    rest_b = b[~b.bbref_id.isin(by_name.bbref_id)]
    rest_n = n[~n.player_id.isin(by_name.player_id)]
    stat = rest_b.merge(
        rest_n[["season", "gp", "min", "player_id"]],
        left_on=["season", "g"],
        right_on=["season", "gp"],
    )
    stat = stat[(stat["mp"] - stat["min"]).abs() <= 2]
    # A stat-line match is only trusted when it is unique within its season.
    stat = stat[~stat.duplicated(subset=["season", "bbref_id"], keep=False)]
    stat = stat[~stat.duplicated(subset=["season", "player_id"], keep=False)]
    by_stat = _unique_pairs(stat)
    by_stat["method"] = "statline"

    return pd.concat([by_name, by_stat], ignore_index=True)


def match_by_name(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """Name-only match for rows with no stats (e.g. rookies on contracts). Unique names only.

    left needs bbref_id, player_name; right needs player_id, player_name.
    """
    lk = left[["bbref_id", "player_name"]].drop_duplicates("bbref_id")
    rk = right[["player_id", "player_name"]].drop_duplicates("player_id")
    lk = lk.assign(key=lk.player_name.map(normalize_name))
    rk = rk.assign(key=rk.player_name.map(normalize_name))
    rk = rk[~rk.key.duplicated(keep=False)]
    return _unique_pairs(lk.merge(rk[["key", "player_id"]], on="key"))
