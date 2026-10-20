from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from data import config, db, quality

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "data_overview_template.html"
OUTPUT = HERE / "data_overview.html"

TABLES = {
    "pbp_events": (
        "Maçtaki her olay: şut, ribaund, faul, oyuncu değişikliği. Şutlarda saha koordinatı ve mesafe var.",
        "Stats Analyst agent'ının text-to-SQL sorguları",
        [
            "game_id",
            "period",
            "clock_seconds",
            "player_name",
            "action_type",
            "sub_type",
            "shot_distance",
            "points",
        ],
    ),
    "player_game_logs": (
        "Her oyuncunun her maçtaki kutu skoru.",
        "Form, trend ve sakatlık sonrası performans",
        ["game_date", "player_name", "team_abbreviation", "matchup", "min", "pts", "reb", "ast"],
    ),
    "player_season_stats": (
        "NBA.com sezon totalleri ve advanced metrikler (USG%, TS%, net rating).",
        "Değerleme modelinin özellikleri",
        ["season", "player_name", "team_abbreviation", "age", "gp", "pts", "ts_pct", "usg_pct"],
    ),
    "player_season_advanced": (
        "Basketball-Reference metrikleri: Win Shares, BPM, VORP, PER.",
        "Değerleme modelinin hedefi (gelecek sezon WS)",
        ["season", "player_name", "position", "g", "mp", "ws", "bpm", "vorp"],
    ),
    "players": (
        "Oyuncu biyografisi: boy, kilo, ülke, draft bilgisi.",
        "Model özellikleri ve oyuncu aramaları",
        [
            "player_name",
            "position",
            "height_in",
            "weight_lb",
            "country",
            "draft_year",
            "draft_number",
        ],
    ),
    "contracts": (
        "2026-27'den 2031-32'ye maaşlar, player ve team option bilgisi.",
        "Kural motoru: maaş eşleştirme ve apron hesapları",
        ["player_name", "season", "salary", "option_type"],
    ),
    "rosters": (
        "2026-27 kadroları, two-way işareti ve kadroya katılma şekli.",
        "Kural motoru: kadro limiti",
        ["player_name", "position", "experience", "is_two_way", "how_acquired"],
    ),
    "draft_picks": (
        "2027-2033 draft pick sahipliği, swap hakları ve koşullu pick'ler.",
        "Stepien kuralı ve 'pick'lerimizi koru' kısıtı",
        ["asset_id", "kind", "original_teams", "description", "protection"],
    ),
    "team_season_stats": (
        "Takım sezon özetleri: galibiyet, rating, tempo.",
        "Bağlam ve takım gücü",
        ["season", "w", "l", "off_rating", "def_rating", "net_rating", "pace"],
    ),
    "teams": (
        "30 takım, NBA.com ve Basketball-Reference kısaltmaları.",
        "Tüm tabloların takım referansı",
        ["abbreviation", "bbref_abbreviation", "full_name", "conference", "division"],
    ),
    "injuries": (
        "Sakatlık raporları. Henüz boş, Faz 4'te Scout agent'ı dolduracak.",
        "Scout agent'ı",
        ["player_id", "report_date", "status", "description"],
    ),
}

CHECK_LABELS = {
    "30 teams": "30 takım var",
    "every season has 400+ players": "Her sezonda 400+ oyuncu var",
    "every season has 30 teams with stats": "Her sezonda 30 takımın istatistiği var",
    ">=98% of minutes have advanced (bbref) metrics": "Dakikaların %98+'ının BBRef metriği var",
    "bbref games match nba games for matched rows (>=97%)": "BBRef ve NBA.com maç sayıları tutuyor (%97+)",
    "percentages are fractions": "Tüm yüzdeler 0–1 aralığında",
    "rosters cover 30 teams": "Kadrolar 30 takımı kapsıyor",
    ">=95% of current-season contracts map to an NBA.com player": "Güncel kontratların %95+'ı bir oyuncuyla eşleşiyor",
    "current-season contracts map to a team": "Her güncel kontratın bir takımı var",
    "draft picks: every team has one own-pick asset per draft and round": "Her takımın her yıl ve tur için tek bir kendi pick'i var",
    "draft picks loaded (30 teams x 7 drafts x 2 rounds)": "420 pick yüklü (30 takım × 7 yıl × 2 tur)",
    "no negative salaries": "Negatif maaş yok",
    "game logs sum to season totals (points, >=99% of player-seasons)": "Maç logları sezon toplamlarını veriyor (%99+)",
    "play-by-play points match box scores (>=99.5% of player-games)": "Play-by-play sayıları kutu skorlarıyla tutuyor (%99.5+)",
    "every box-score game has play-by-play (up to the last date covered)": "Her maçın play-by-play'i var",
}

SAMPLE_WHERE = {
    "pbp_events": "WHERE game_id = (SELECT max(game_id) FROM pbp_events) AND action_type IN ('Made Shot', 'Missed Shot')",
    "player_game_logs": "WHERE season = '2025-26' ORDER BY pts DESC",
    "player_season_stats": "WHERE season = '2025-26' ORDER BY pts DESC",
    "player_season_advanced": "WHERE season = '2025-26' ORDER BY ws DESC",
    "players": "WHERE draft_year IS NOT NULL ORDER BY draft_year DESC, draft_number",
    "contracts": "ORDER BY salary DESC",
    "rosters": "ORDER BY is_two_way DESC",
    "draft_picks": "WHERE kind <> 'own' ORDER BY year, round",
    "team_season_stats": "WHERE season = '2025-26' ORDER BY net_rating DESC",
    "teams": "ORDER BY abbreviation",
    "injuries": "",
}


def rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    df = con.execute(sql).df()
    return json.loads(df.to_json(orient="records", date_format="iso"))


def table_profiles(con) -> list[dict]:
    out = []
    for name, (desc, use, sample_cols) in TABLES.items():
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        columns = [{"name": c[0], "type": c[1]} for c in con.execute(f"DESCRIBE {name}").fetchall()]
        sample = rows(
            con, f"SELECT {', '.join(sample_cols)} FROM {name} {SAMPLE_WHERE[name]} LIMIT 4"
        )
        out.append(
            {"name": name, "rows": n, "description": desc, "use": use,
             "columns": columns, "sample_columns": sample_cols, "sample": sample}
        )  # fmt: skip
    return out


def league_trends(con) -> list[dict]:
    return rows(
        con,
        """
        WITH p AS (
            SELECT season,
                   sum(fg3a) / sum(fga) AS three_rate,
                   sum(pts) / (2 * (sum(fga) + 0.44 * sum(fta))) AS ts,
                   avg(age) FILTER (WHERE min >= 500) AS avg_age
            FROM player_season_stats GROUP BY 1),
        t AS (SELECT season, avg(pace) AS pace, avg(pts) AS team_ppg FROM team_season_stats GROUP BY 1)
        SELECT season, round(three_rate, 4) AS three_rate, round(ts, 4) AS ts,
               round(avg_age, 2) AS avg_age, round(pace, 1) AS pace, round(team_ppg, 1) AS team_ppg
        FROM p JOIN t USING (season) ORDER BY season
        """,
    )


def shot_zones(con) -> list[dict]:
    return rows(
        con,
        """
        SELECT season,
               round(avg((shot_distance < 4 AND shot_value = 2)::int), 4) AS rim,
               round(avg((shot_distance BETWEEN 4 AND 13 AND shot_value = 2)::int), 4) AS short_mid,
               round(avg((shot_distance >= 14 AND shot_value = 2)::int), 4) AS long_mid,
               round(avg((shot_value = 3)::int), 4) AS three
        FROM pbp_events WHERE is_field_goal GROUP BY 1 ORDER BY 1
        """,
    )


def shot_grid(con) -> dict:
    data = rows(
        con,
        """
        SELECT season, floor((x + 250) / 20)::int AS gx, floor((y + 50) / 20)::int AS gy,
               count(*) AS fga, sum((shot_result = 'Made')::int) AS fgm
        FROM pbp_events
        WHERE is_field_goal AND x BETWEEN -250 AND 249 AND y BETWEEN -50 AND 369
        GROUP BY ALL
        """,
    )
    grid: dict[str, list] = {}
    for r in data:
        grid.setdefault(r["season"], []).append([r["gx"], r["gy"], r["fga"], r["fgm"]])
    return grid


def ws_profile(con) -> dict:
    hist = rows(
        con,
        """
        SELECT floor(ws) AS bin, count(*) AS n FROM player_season_advanced
        WHERE mp >= 500 GROUP BY 1 ORDER BY 1
        """,
    )
    stats = rows(
        con,
        """
        SELECT count(*) AS n, round(avg(ws), 2) AS mean, round(median(ws), 2) AS median,
               round(quantile_cont(ws, 0.9), 2) AS p90, round(max(ws), 1) AS max
        FROM player_season_advanced WHERE mp >= 500
        """,
    )[0]
    pairs = rows(
        con,
        """
        WITH a AS (SELECT player_id, season, ws, mp FROM player_season_advanced)
        SELECT count(*) AS pairs, round(corr(a1.ws, a2.ws), 3) AS autocorr
        FROM a a1 JOIN a a2 ON a1.player_id = a2.player_id
         AND cast(left(a2.season, 4) AS int) = cast(left(a1.season, 4) AS int) + 1
        WHERE a1.mp >= 500 AND a2.mp >= 500
        """,
    )[0]
    top = rows(
        con,
        """
        SELECT a.player_name, s.team_abbreviation AS team, a.age, a.g, round(a.ws, 1) AS ws,
               round(a.bpm, 1) AS bpm, round(a.vorp, 1) AS vorp, round(s.pts / s.gp, 1) AS ppg,
               round(s.ts_pct, 3) AS ts
        FROM player_season_advanced a JOIN player_season_stats s USING (player_id, season)
        WHERE season = '2025-26' ORDER BY a.ws DESC LIMIT 30
        """,
    )
    return {"hist": hist, "stats": stats | pairs, "top": top}


def payroll(con) -> list[dict]:
    teams = rows(
        con,
        """
        SELECT t.abbreviation AS team, t.full_name AS name,
               sum(salary) FILTER (WHERE season = '2026-27') AS y1,
               sum(salary) FILTER (WHERE season = '2027-28') AS y2,
               count(*) FILTER (WHERE season = '2026-27') AS contracts
        FROM contracts c JOIN teams t USING (team_id) GROUP BY 1, 2 ORDER BY y1 DESC
        """,
    )
    top = rows(
        con,
        """
        SELECT t.abbreviation AS team, player_name, salary, option_type,
               (SELECT count(*) FROM contracts c2 WHERE c2.bbref_id = c.bbref_id) AS years
        FROM contracts c JOIN teams t USING (team_id)
        WHERE season = '2026-27'
        QUALIFY row_number() OVER (PARTITION BY t.abbreviation ORDER BY salary DESC) <= 5
        """,
    )
    by_team: dict[str, list] = {}
    for r in top:
        by_team.setdefault(r["team"], []).append(r)
    for t in teams:
        t["top"] = sorted(by_team.get(t["team"], []), key=lambda r: -r["salary"])
    return teams


def picks(con) -> dict:
    data = rows(
        con,
        """
        SELECT d.year, d.round, d.kind, d.original_teams, d.description, d.protection,
               o.abbreviation AS owner, coalesce(og.abbreviation, '') AS original
        FROM draft_picks d
        JOIN teams o ON o.team_id = d.owner_team_id
        LEFT JOIN teams og ON og.team_id = d.original_team_id
        """,
    )
    return {"teams": sorted({r["owner"] for r in data}), "assets": data}


def pbp_reconciliation(con) -> list[dict]:
    return rows(
        con,
        """
        WITH p AS (SELECT game_id, player_id, sum(points) AS pts FROM pbp_events GROUP BY ALL),
        e AS (SELECT season, count(*) AS events, count(DISTINCT game_id) AS games
              FROM pbp_events GROUP BY 1)
        SELECT g.season, any_value(e.games) AS games, any_value(e.events) AS events,
               count(*) AS player_games,
               round(100 * avg((coalesce(p.pts, 0) = g.pts)::int), 3) AS match_pct
        FROM player_game_logs g LEFT JOIN p USING (game_id, player_id) JOIN e USING (season)
        GROUP BY 1 ORDER BY 1
        """,
    )


def build_payload(con) -> dict:
    tables = table_profiles(con)
    failures = quality.run_checks(con)
    summary = rows(
        con,
        """
        SELECT count(DISTINCT season) AS seasons, count(DISTINCT game_id) AS games,
               count(DISTINCT player_id) AS players, min(game_date) AS first_game,
               max(game_date) AS last_game
        FROM player_game_logs
        """,
    )[0]
    summary["total_rows"] = sum(t["rows"] for t in tables)
    summary["pbp_rows"] = next(t["rows"] for t in tables if t["name"] == "pbp_events")
    checks = [d for d, _, _ in quality.CHECKS] + [quality.GAME_LOG_CHECK[0]]
    checks += [d for d, _, _ in quality.PBP_CHECKS]
    checks = [CHECK_LABELS.get(c, c) for c in checks]
    return {
        "summary": summary,
        "tables": tables,
        "trends": league_trends(con),
        "zones": shot_zones(con),
        "shots": shot_grid(con),
        "ws": ws_profile(con),
        "payroll": payroll(con),
        "picks": picks(con),
        "pbp": pbp_reconciliation(con),
        "quality": {"checks": checks, "failures": failures},
    }


def render(payload: dict, fragment: bool) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    if fragment:
        return html
    return (
        '<!doctype html>\n<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"</head>\n<body>\n{html}\n</body>\n</html>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the interactive data overview page")
    parser.add_argument("--db", type=Path, default=config.default_db_path())
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--fragment", action="store_true")
    args = parser.parse_args()
    con = db.connect(args.db, read_only=True)
    payload = build_payload(con)
    con.close()
    args.out.write_text(render(payload, args.fragment), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
