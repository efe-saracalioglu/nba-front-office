from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import duckdb

from data.crosswalk import normalize_name
from rules.models import PickAsset, Player, TeamState
from rules.season import SeasonConfig, load_season

_SIGNED = re.compile(r"^(?:Signed|Awarded on Waivers) on (\d{2}/\d{2}/\d{2})")
_TRADED = re.compile(r"Traded from \w{3} on (\d{2}/\d{2}/\d{2})")


def _match_date(pattern: re.Pattern, text: str) -> date | None:
    m = pattern.search(text)
    return datetime.strptime(m.group(1), "%m/%d/%y").date() if m else None


def parse_how_acquired(text: str | None) -> tuple[date | None, date | None]:
    if not text:
        return None, None
    traded = None if text.startswith("Draft Rights") else _match_date(_TRADED, text)
    return _match_date(_SIGNED, text), traded


@dataclass
class LeagueState:
    season: SeasonConfig
    teams: dict[str, TeamState]
    picks: dict[str, PickAsset] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._players = {p.player_id: p for t in self.teams.values() for p in t.players}

    def player(self, player_id: int) -> Player | None:
        return self._players.get(player_id)

    def find_player(self, name: str, team: str | None = None) -> Player | None:
        needle = normalize_name(name)
        hits = [
            p for p in self._players.values()
            if normalize_name(p.name) == needle and (team is None or p.team == team)
        ]  # fmt: skip
        return hits[0] if len(hits) == 1 else None

    def first_round_holdings(
        self, team: str, owners: dict[str, str] | None = None
    ) -> dict[int, int]:
        owners = owners or {}
        out = {
            y: 0
            for y in range(
                self.season.draft.first_tradable_year, self.season.draft.last_tradable_year + 1
            )
        }
        for a in self.picks.values():
            if a.round == 1 and a.counts_as_pick and owners.get(a.asset_id, a.owner) == team:
                out[a.year] = out.get(a.year, 0) + 1
        return out


def load_league(
    db_path: str | Path | None = None,
    season: str | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> LeagueState:
    from data import db

    cfg = load_season(season) if season else load_season()
    owns_connection = con is None
    con = con or db.connect(db_path, read_only=True)
    try:
        roster = con.execute(
            """
            SELECT r.player_id, r.player_name, t.abbreviation AS team, r.is_two_way,
                   r.how_acquired, c.salary
            FROM rosters r
            JOIN teams t USING (team_id)
            LEFT JOIN contracts c
              ON c.player_id = r.player_id AND c.season = r.season AND c.team_id = r.team_id
            WHERE r.season = ?
            """,
            [cfg.season],
        ).fetchall()
        dead = con.execute(
            """
            SELECT t.abbreviation, sum(c.salary)
            FROM contracts c JOIN teams t USING (team_id)
            WHERE c.season = ?
              AND (c.player_id IS NULL OR c.player_id NOT IN (
                    SELECT player_id FROM rosters WHERE season = ? AND team_id = c.team_id))
            GROUP BY 1
            """,
            [cfg.season, cfg.season],
        ).fetchall()
        picks = con.execute(
            """
            SELECT d.asset_id, d.year, d.round, o.abbreviation, og.abbreviation, d.kind,
                   coalesce(d.description, ''), d.protection
            FROM draft_picks d
            JOIN teams o ON o.team_id = d.owner_team_id
            LEFT JOIN teams og ON og.team_id = d.original_team_id
            """
        ).fetchall()
        abbrs = [r[0] for r in con.execute("SELECT abbreviation FROM teams").fetchall()]
    finally:
        if owns_connection:
            con.close()

    teams = {a: TeamState(team=a) for a in abbrs}
    for pid, name, team, two_way, how, salary in roster:
        signed_on, traded_on = parse_how_acquired(how)
        teams[team].players.append(
            Player(
                player_id=pid, name=name, team=team, salary=salary, is_two_way=bool(two_way),
                signed_on=signed_on, acquired_by_trade_on=traded_on,
            )
        )  # fmt: skip
    for team, amount in dead:
        teams[team].dead_money = int(amount)
    pick_assets = {
        r[0]: PickAsset(
            asset_id=r[0], year=r[1], round=r[2], owner=r[3], original=r[4], kind=r[5],
            description=r[6], protection=r[7],
        )
        for r in picks
    }  # fmt: skip
    return LeagueState(season=cfg, teams=teams, picks=pick_assets)
