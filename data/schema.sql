-- Front Office warehouse. Seasons are labels like '2024-25'.
-- Money is in whole US dollars. player_id / team_id are NBA.com ids.
-- Every *_pct / *_rate column is a 0-1 fraction (0.585, not 58.5).

CREATE TABLE IF NOT EXISTS teams (
    team_id           BIGINT PRIMARY KEY,
    abbreviation      VARCHAR NOT NULL,   -- NBA.com style: BKN, CHA, PHX
    bbref_abbreviation VARCHAR NOT NULL,  -- Basketball-Reference style: BRK, CHO, PHO
    full_name         VARCHAR NOT NULL,
    city              VARCHAR,
    nickname          VARCHAR,
    conference        VARCHAR,
    division          VARCHAR
);

CREATE TABLE IF NOT EXISTS players (
    player_id         BIGINT PRIMARY KEY,
    bbref_id          VARCHAR,
    player_name       VARCHAR NOT NULL,
    birth_date        DATE,
    height_in         INTEGER,
    weight_lb         INTEGER,
    country           VARCHAR,
    college           VARCHAR,
    draft_year        INTEGER,            -- NULL when undrafted
    draft_round       INTEGER,
    draft_number      INTEGER,
    position          VARCHAR             -- latest listed position (PG/SG/SF/PF/C)
);

-- One row per player per regular season (totals; traded players aggregated).
CREATE TABLE IF NOT EXISTS player_season_stats (
    player_id         BIGINT NOT NULL,
    season            VARCHAR NOT NULL,
    player_name       VARCHAR NOT NULL,
    team_id           BIGINT,             -- last team that season
    team_abbreviation VARCHAR,
    age               DOUBLE,
    gp                INTEGER,
    min               DOUBLE,             -- total minutes
    pts INTEGER, reb INTEGER, oreb INTEGER, dreb INTEGER, ast INTEGER,
    stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    plus_minus        DOUBLE,
    off_rating DOUBLE, def_rating DOUBLE, net_rating DOUBLE,
    ast_pct DOUBLE, oreb_pct DOUBLE, dreb_pct DOUBLE, reb_pct DOUBLE,
    tov_pct DOUBLE, efg_pct DOUBLE, ts_pct DOUBLE, usg_pct DOUBLE,
    pace DOUBLE, pie DOUBLE, poss DOUBLE,
    PRIMARY KEY (player_id, season)
);

-- Basketball-Reference advanced metrics (multi-team seasons use the combined row).
CREATE TABLE IF NOT EXISTS player_season_advanced (
    player_id         BIGINT NOT NULL,
    season            VARCHAR NOT NULL,
    bbref_id          VARCHAR NOT NULL,
    player_name       VARCHAR NOT NULL,
    position          VARCHAR,
    age               INTEGER,
    g INTEGER, gs INTEGER, mp INTEGER,
    per DOUBLE, ts_pct DOUBLE, fg3a_rate DOUBLE, fta_rate DOUBLE,
    orb_pct DOUBLE, drb_pct DOUBLE, trb_pct DOUBLE, ast_pct DOUBLE,
    stl_pct DOUBLE, blk_pct DOUBLE, tov_pct DOUBLE, usg_pct DOUBLE,
    ows DOUBLE, dws DOUBLE, ws DOUBLE, ws_per_48 DOUBLE,
    obpm DOUBLE, dbpm DOUBLE, bpm DOUBLE, vorp DOUBLE,
    PRIMARY KEY (player_id, season)
);

CREATE TABLE IF NOT EXISTS player_game_logs (
    game_id           VARCHAR NOT NULL,
    player_id         BIGINT NOT NULL,
    season            VARCHAR NOT NULL,
    player_name       VARCHAR NOT NULL,
    team_id           BIGINT NOT NULL,
    team_abbreviation VARCHAR,
    game_date         DATE NOT NULL,
    matchup           VARCHAR,            -- 'GSW vs. LAL' (home) / 'GSW @ LAL' (away)
    wl                VARCHAR,
    min               DOUBLE,
    pts INTEGER, reb INTEGER, oreb INTEGER, dreb INTEGER, ast INTEGER,
    stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    plus_minus        DOUBLE,
    PRIMARY KEY (game_id, player_id)
);

-- Regular-season play-by-play (NBA.com PlayByPlayV3 schema), one row per event.
-- Order events with event_index; action_number is the feed's id and is NOT chronological.
CREATE TABLE IF NOT EXISTS pbp_events (
    game_id           VARCHAR NOT NULL,   -- joins player_game_logs.game_id
    season            VARCHAR NOT NULL,
    event_index       INTEGER NOT NULL,   -- 0-based chronological order within the game
    action_number     INTEGER NOT NULL,   -- feed id; steals/blocks share it with their parent event
    is_secondary      BOOLEAN NOT NULL,   -- TRUE for steals/blocks attached to a turnover/miss
    period            INTEGER NOT NULL,   -- 1-4, 5+ = overtime
    clock_seconds     DOUBLE,             -- seconds remaining in the period
    team_id           BIGINT,
    player_id         BIGINT,
    player_name       VARCHAR,            -- last name as shown in the feed
    action_type       VARCHAR NOT NULL,   -- 'Made Shot' | 'Missed Shot' | 'Free Throw' | 'Rebound' | 'Turnover' | 'Steal' | 'Block' | 'Foul' | 'Substitution' | ...
    sub_type          VARCHAR,            -- e.g. 'Cutting Layup Shot', 'Offensive'
    description       VARCHAR,
    shot_result       VARCHAR,            -- 'Made' | 'Missed' for field goals
    is_field_goal     BOOLEAN NOT NULL,
    shot_value        INTEGER,            -- 2 or 3 for field goals, else 0
    shot_distance     INTEGER,            -- feet
    x INTEGER, y INTEGER,                 -- shot location, legacy court coordinates
    location          VARCHAR,            -- 'h' home | 'v' visitor
    score_home        INTEGER,            -- score after this event, only on scoring rows
    score_away        INTEGER,
    points            INTEGER NOT NULL,   -- points scored on this event (0 for non-scoring)
    PRIMARY KEY (game_id, event_index)
);

CREATE TABLE IF NOT EXISTS team_season_stats (
    team_id           BIGINT NOT NULL,
    season            VARCHAR NOT NULL,
    gp INTEGER, w INTEGER, l INTEGER, w_pct DOUBLE,
    pts DOUBLE, plus_minus DOUBLE,     -- per game
    off_rating DOUBLE, def_rating DOUBLE, net_rating DOUBLE, pace DOUBLE,
    PRIMARY KEY (team_id, season)
);

-- Current-season rosters from NBA.com.
CREATE TABLE IF NOT EXISTS rosters (
    team_id           BIGINT NOT NULL,
    season            VARCHAR NOT NULL,
    player_id         BIGINT NOT NULL,
    player_name       VARCHAR NOT NULL,
    jersey            VARCHAR,
    position          VARCHAR,
    birth_date        DATE,
    experience        VARCHAR,           -- 'R' for rookies
    how_acquired      VARCHAR,
    is_two_way        BOOLEAN NOT NULL,  -- two-way contracts don't count toward the 15-man limit
    PRIMARY KEY (team_id, season, player_id)
);

-- Salary by player and season (snapshot of Basketball-Reference contracts page).
CREATE TABLE IF NOT EXISTS contracts (
    bbref_id          VARCHAR NOT NULL,
    player_id         BIGINT,             -- NULL when no NBA.com match was found
    player_name       VARCHAR NOT NULL,
    team_id           BIGINT,
    season            VARCHAR NOT NULL,
    salary            BIGINT NOT NULL,
    option_type       VARCHAR NOT NULL,   -- 'none' | 'player' | 'team'
    snapshot_date     DATE NOT NULL,
    PRIMARY KEY (bbref_id, season)
);

-- Future draft pick ownership, rebuilt by replaying pick trades since 2019-20
-- (python -m data.draft_picks; see data/seed/pick_overrides.yaml for manual resolutions).
-- One row per asset. A team still holding its own pick has kind = 'own'.
CREATE TABLE IF NOT EXISTS draft_picks (
    asset_id          VARCHAR PRIMARY KEY, -- '2029-1-PHO' for plain picks
    year              INTEGER NOT NULL,    -- draft year
    round             INTEGER NOT NULL,    -- 1 or 2
    owner_team_id     BIGINT NOT NULL,
    original_team_id  BIGINT,              -- NULL when the asset depends on several teams' picks
    original_teams    VARCHAR NOT NULL,    -- comma-separated NBA abbreviations, e.g. 'MIN,UTA'
    kind              VARCHAR NOT NULL,    -- 'own' | 'acquired' | 'swap_right' | 'conditional'
    description       VARCHAR,             -- e.g. 'more favorable of MIN and UTA'
    protection        VARCHAR,             -- e.g. 'top-4 protected'
    last_trade        VARCHAR,             -- trade_key of the latest transfer
    inferred          BOOLEAN NOT NULL     -- TRUE when a transfer had no annotation and was inferred
);

-- Populated by the Scout news pipeline (Phase 4).
CREATE TABLE IF NOT EXISTS injuries (
    player_id         BIGINT NOT NULL,
    report_date       DATE NOT NULL,
    status            VARCHAR,           -- 'Out' | 'Doubtful' | 'Questionable' | ...
    description       VARCHAR,
    source            VARCHAR,
    PRIMARY KEY (player_id, report_date)
);

CREATE TABLE IF NOT EXISTS etl_runs (
    table_name        VARCHAR NOT NULL,
    rows_loaded       BIGINT NOT NULL,
    source            VARCHAR,
    loaded_at         TIMESTAMP NOT NULL DEFAULT current_timestamp
);
