# Example queries for the Front Office warehouse (DuckDB)

Conventions that trip people up:
- `season` is a label like `'2024-25'`; compare and sort it as text.
- Every `*_pct` / `*_rate` column is a 0-1 fraction, so 38% is `0.38`.
- Order play-by-play with `event_index`, never `action_number`.
- `player_season_stats` holds NBA.com totals; `player_season_advanced` holds Win Shares, BPM and VORP. Join them on `(player_id, season)`.
- Money is whole dollars; current contracts are in season `'2026-27'`.

## Top scorers per game in a season
```sql
SELECT player_name, team_abbreviation, gp, round(pts / gp, 1) AS ppg
FROM player_season_stats
WHERE season = '2025-26' AND gp >= 40
ORDER BY ppg DESC
LIMIT 10;
```

## Win Shares leaders with their scoring
```sql
SELECT a.player_name, s.team_abbreviation, round(a.ws, 1) AS ws, round(a.bpm, 1) AS bpm,
       round(s.pts / s.gp, 1) AS ppg
FROM player_season_advanced a
JOIN player_season_stats s USING (player_id, season)
WHERE a.season = '2025-26'
ORDER BY a.ws DESC
LIMIT 10;
```

## A player's last five games
```sql
SELECT game_date, matchup, wl, round(min, 1) AS min, pts, reb, ast
FROM player_game_logs
WHERE player_name = 'Nikola Jokić'
ORDER BY game_date DESC
LIMIT 5;
```

## Three-point shooting by distance band for one player (play-by-play)
```sql
SELECT CASE WHEN shot_distance < 25 THEN 'under 25 ft' ELSE '25+ ft' END AS band,
       count(*) AS attempts,
       round(avg((shot_result = 'Made')::int), 3) AS fg_pct
FROM pbp_events
WHERE season = '2025-26' AND is_field_goal AND shot_value = 3
  AND player_id = (SELECT player_id FROM players WHERE player_name = 'Stephen Curry')
GROUP BY 1
ORDER BY 1;
```

## Clutch scoring: points in the last five minutes of the fourth quarter or overtime
```sql
SELECT p.player_name, sum(e.points) AS clutch_points
FROM pbp_events e
JOIN players p USING (player_id)
WHERE e.season = '2025-26' AND e.period >= 4 AND e.clock_seconds <= 300
GROUP BY 1
ORDER BY clutch_points DESC
LIMIT 10;
```

## Team payroll for the current season
```sql
SELECT t.abbreviation, round(sum(c.salary) / 1e6, 1) AS payroll_m, count(*) AS contracts
FROM contracts c JOIN teams t USING (team_id)
WHERE c.season = '2026-27'
GROUP BY 1
ORDER BY payroll_m DESC;
```

## Players with a player option next season
```sql
SELECT c.player_name, t.abbreviation, c.salary
FROM contracts c JOIN teams t USING (team_id)
WHERE c.season = '2027-28' AND c.option_type = 'player'
ORDER BY c.salary DESC;
```

## Centers on a team with their projection and contract value
```sql
SELECT p.player_name, p.position, round(j.projected_ws, 1) AS projected_ws,
       round(j.salary / 1e6, 1) AS salary_m, round(j.surplus_value / 1e6, 1) AS surplus_m
FROM player_projections j
JOIN players p USING (player_id)
JOIN teams t ON t.team_id = j.team_id
WHERE t.abbreviation = 'BOS' AND p.position = 'C'
ORDER BY projected_ws DESC;
```

## Who owns a team's future first-round picks
```sql
SELECT d.year, d.kind, o.abbreviation AS owner, d.protection
FROM draft_picks d
JOIN teams o ON o.team_id = d.owner_team_id
WHERE d.round = 1 AND d.original_teams LIKE '%PHX%'
ORDER BY d.year;
```

## Current injury report for a team
```sql
SELECT r.player_name, i.status, i.report_date, i.description
FROM injuries i
JOIN rosters r USING (player_id)
JOIN teams t ON t.team_id = r.team_id
WHERE t.abbreviation = 'ATL'
ORDER BY i.report_date DESC;
```

## Team net rating and record by season
```sql
SELECT t.abbreviation, s.season, s.w, s.l, s.net_rating
FROM team_season_stats s JOIN teams t USING (team_id)
WHERE s.season = '2025-26'
ORDER BY s.net_rating DESC;
```
