import pandas as pd

from data.sources.pbp_archive import clock_to_seconds, transform


def _event(n, period, clock, action, desc, pid=1, value=0, home=None, away=None):
    return {
        "gameId": 22500001, "actionNumber": n, "clock": clock, "period": period,
        "teamId": 1610612760, "teamTricode": "OKC", "personId": pid, "playerName": "X",
        "playerNameI": "X", "xLegacy": 0, "yLegacy": 0, "shotDistance": 0,
        "shotResult": "Made" if action == "Made Shot" else None,
        "isFieldGoal": int(action in ("Made Shot", "Missed Shot")),
        "scoreHome": home, "scoreAway": away, "pointsTotal": 0, "location": "h",
        "description": desc, "actionType": action, "subType": None, "videoAvailable": 1,
        "shotValue": value, "actionId": n,
    }  # fmt: skip


RAW = pd.DataFrame(
    [
        _event(2, 1, "PT12M00.00S", "period", "Start of 1st Period", pid=0),
        _event(10, 1, "PT11M30.00S", "Made Shot", "A 25' 3PT (3 PTS)", value=3, home=3, away=0),
        _event(12, 1, "PT11M00.00S", "Turnover", "A Bad Pass Turnover"),
        _event(12, 1, "PT11M00.00S", None, "B STEAL (1 STL)", pid=2),
        _event(14, 1, "PT10M40.00S", "Free Throw", "MISS A Free Throw 1 of 2"),
        _event(15, 1, "PT10M40.00S", "Free Throw", "A Free Throw 2 of 2 (4 PTS)", home=4, away=0),
        _event(900, 1, "PT10M50.00S", "Foul", "C S.FOUL", pid=3),
        _event(800, 4, "PT00M00.00S", "period", "End of 4th Period", pid=0),
    ]
)


def test_clock_to_seconds():
    assert clock_to_seconds(pd.Series(["PT11M36.00S", "PT00M03.20S"])).tolist() == [696.0, 3.2]


def test_events_are_ordered_by_game_clock_not_action_number():
    df = transform(RAW, "2025-26")
    assert df["event_index"].tolist() == list(range(len(RAW)))
    assert df["action_number"].tolist() == [2, 10, 12, 12, 900, 14, 15, 800]


def test_points_come_from_events():
    df = transform(RAW, "2025-26")
    assert df.groupby("player_id")["points"].sum().to_dict() == {1: 4, 2: 0, 3: 0}


def test_secondary_events_get_a_type():
    df = transform(RAW, "2025-26")
    steal = df[df.description.str.contains("STEAL")].iloc[0]
    assert steal.action_type == "Steal"
    assert bool(steal.is_secondary)
    assert df.action_type.notna().all()


def test_game_id_and_nulls():
    df = transform(RAW, "2025-26")
    assert set(df.game_id) == {"0022500001"}
    assert df[df.action_type == "period"].player_id.isna().all()
    assert df.score_home.isna().sum() == 6


def test_shot_value_derived_when_archive_lacks_it():
    df = transform(RAW.drop(columns="shotValue"), "2010-11")
    assert df.groupby("player_id")["points"].sum().to_dict() == {1: 4, 2: 0, 3: 0}
    assert df.loc[df.action_type == "Made Shot", "shot_value"].tolist() == [3]
