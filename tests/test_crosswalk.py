import pandas as pd
import pytest

from data.crosswalk import build_crosswalk, match_by_name, normalize_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Nikola Jokić", "nikola jokic"),
        ("Jaren Jackson Jr.", "jaren jackson"),
        ("Gary Trent Jr", "gary trent"),
        ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
        ("De'Aaron Fox", "deaaron fox"),
        ("P.J. Washington", "pj washington"),
        ("Robert Williams III", "robert williams"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def _bbref(rows):
    return pd.DataFrame(rows, columns=["bbref_id", "player_name", "season", "g", "mp"])


def _nba(rows):
    return pd.DataFrame(rows, columns=["player_id", "player_name", "season", "gp", "min"])


def test_name_then_statline_match():
    bbref = _bbref(
        [
            ("jokicni01", "Nikola Jokić", "2024-25", 70, 2571),
            ("claxtni01", "Nicolas Claxton", "2024-25", 70, 1800),
        ]
    )
    nba = _nba(
        [
            (203999, "Nikola Jokic", "2024-25", 70, 2571.4),
            (1629651, "Nic Claxton", "2024-25", 70, 1800.6),
        ]
    )
    xw = build_crosswalk(bbref, nba).set_index("bbref_id")
    assert xw.loc["jokicni01", "player_id"] == 203999
    assert xw.loc["jokicni01", "method"] == "name"
    assert xw.loc["claxtni01", "player_id"] == 1629651
    assert xw.loc["claxtni01", "method"] == "statline"


def test_name_match_carries_across_seasons():
    bbref = _bbref([("a01", "Al Pha", "2023-24", 10, 100), ("a01", "Al Pha", "2024-25", 20, 200)])
    nba = _nba([(1, "Al Pha", "2023-24", 10, 100), (1, "Al Pha", "2024-25", 20, 200)])
    xw = build_crosswalk(bbref, nba)
    assert len(xw) == 1


def test_same_name_same_season_is_not_guessed_by_name():
    bbref = _bbref(
        [
            ("willima01", "Marcus Williams", "2012-13", 5, 40),
            ("willima02", "Marcus Williams", "2012-13", 60, 1500),
        ]
    )
    nba = _nba(
        [
            (10, "Marcus Williams", "2012-13", 60, 1500.2),
            (11, "Marcus Williams", "2012-13", 5, 39.9),
        ]
    )
    xw = build_crosswalk(bbref, nba).set_index("bbref_id")
    assert xw.loc["willima01", "player_id"] == 11
    assert xw.loc["willima02", "player_id"] == 10
    assert set(xw.method) == {"statline"}


def test_ambiguous_statline_is_left_unmatched():
    bbref = _bbref([("x01", "Xavier One", "2020-21", 1, 3)])
    nba = _nba([(1, "Ex One", "2020-21", 1, 3.0), (2, "Ex Two", "2020-21", 1, 2.5)])
    assert build_crosswalk(bbref, nba).empty


def test_match_by_name_skips_duplicate_names():
    left = pd.DataFrame({"bbref_id": ["r1", "r2"], "player_name": ["Rook One", "Twin Name"]})
    right = pd.DataFrame(
        {"player_id": [1, 2, 3], "player_name": ["Rook One", "Twin Name", "Twin Name"]}
    )
    out = match_by_name(left, right)
    assert out.to_dict("records") == [{"bbref_id": "r1", "player_id": 1}]
