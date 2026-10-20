from datetime import date

import pytest

from data.draft_picks import Ledger, build_ledger, classify, pool
from data.sources.bbref_transactions import PickTransfer, parse_page


def _page(*paragraphs, day="July 6, 2025"):
    ps = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f'<ul class="page_index"><li><span>{day}</span>{ps}</li></ul>'


TWO_TEAM = (
    'The <a data-attr-from="GSW">Warriors</a> traded Justinian Jessup and a 2032 2nd round '
    'draft pick to the <a data-attr-to="MEM">Grizzlies</a> for Will Richard and a 2030 1st '
    "round draft pick.  2032 2nd-rd pick is GSW own 2030 1st-rd pick is a right to swap "
    "Memphis received a trade exception."
)
THREE_TEAM = (
    'In a 3-team trade, the <a data-attr-from="CHI">Bulls</a> traded DeMar DeRozan to the '
    '<a data-attr-to="SAC">Kings</a>; the <a data-attr-from="SAC">Kings</a> traded cash and a '
    '2028 2nd round draft pick to the <a data-attr-to="CHI">Bulls</a>; and the '
    '<a data-attr-from="SAC">Kings</a> traded Harrison Barnes and a 2031 1st round draft pick '
    'to the <a data-attr-to="SAS">Spurs</a>.  2031 1st-rd pick is a swap 2028 2nd-rd pick is '
    "SAC own Sacramento received a trade exception."
)
NOT_A_TRADE = 'The <a data-attr-to="CHO">Hornets</a> signed X to an Exhibit 10 contract.'


def test_parse_two_team_trade_both_directions():
    ts = {(t.year, t.round): t for t in parse_page(_page(NOT_A_TRADE, TWO_TEAM))}
    second = ts[(2032, 2)]
    assert (second.from_team, second.to_team, second.original_team) == ("GSW", "MEM", "GSW")
    assert second.trade_key == "2025-07-06#1"
    swap = ts[(2030, 1)]
    assert (swap.from_team, swap.to_team) == ("MEM", "GSW")
    assert swap.annotation == "a right to swap" and swap.complex


def test_parse_multi_team_trade_legs():
    ts = {(t.year, t.round): t for t in parse_page(_page(THREE_TEAM))}
    assert (ts[(2028, 2)].from_team, ts[(2028, 2)].to_team) == ("SAC", "CHI")
    assert ts[(2028, 2)].original_team == "SAC"
    assert (ts[(2031, 1)].from_team, ts[(2031, 1)].to_team) == ("SAC", "SAS")
    assert ts[(2031, 1)].annotation == "a swap"


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (None, ("none", None, None)),
        ("PHO own", ("simple", "PHO", None)),
        ("MIN own conditional", ("simple", "MIN", "conditional")),
        ("a right to swap", ("swap", None, None)),
        ("more favorable of LAL and WAS", ("conditional", None, None)),
        ("top-8 protected", ("simple_unknown_original", None, "top-8 protected")),
    ],
)
def test_classify(annotation, expected):
    assert classify(annotation) == expected


def test_pool():
    assert pool("more favorable of LAL and WAS") == ["LAL", "WAS"]
    assert pool("least favorable of OKC, LAC, and HOU") == ["OKC", "LAC", "HOU"]
    assert pool("least favorable of ORL/DET/MIL, became DET") == ["ORL", "DET", "MIL"]
    assert pool("more favorable") == []


def _t(key, year, rnd, frm, to, ann):
    original = classify(ann)[1] if classify(ann)[0] == "simple" else None
    return PickTransfer(key, date(2025, 1, 1), year, rnd, frm, to, original, ann, False, "")


def test_ledger_chain_and_conflict():
    years = range(2027, 2028)
    ledger = build_ledger(
        [
            _t("a#0", 2027, 1, "BOS", "SAS", "BOS own"),
            _t("b#0", 2027, 1, "SAS", "UTA", "BOS own"),
            _t("c#0", 2027, 1, "MIA", "OKC", "BOS own"),
        ],
        years,
        {},
    )
    pick = ledger.assets["2027-1-BOS"]
    assert pick.owner == "OKC" and pick.kind == "acquired"
    assert [r["reason"] for r in ledger.review] == ["conflict: 2027-1-BOS owned by UTA, not MIA"]


def test_ledger_swap_right_is_moved_when_retraded():
    ledger = build_ledger(
        [
            _t("a#0", 2028, 1, "CLE", "UTA", "a right to swap"),
            _t("b#0", 2028, 1, "UTA", "OKC", "a right to swap"),
        ],
        range(2028, 2029),
        {},
    )
    swaps = [a for a in ledger.assets.values() if a.kind == "swap_right"]
    assert len(swaps) == 1 and swaps[0].owner == "OKC" and swaps[0].originals == ["CLE"]
    assert ledger.assets["2028-1-CLE"].owner == "CLE"


def test_ledger_unannotated_pick_is_inferred_as_givers_own():
    ledger = build_ledger([_t("a#0", 2027, 2, "IND", "OKC", None)], range(2027, 2028), {})
    assert ledger.assets["2027-2-IND"].owner == "OKC"
    assert ledger.assets["2027-2-IND"].inferred


def test_ledger_override_creates_asset():
    t = _t("a#0", 2031, 1, "SAC", "SAS", "something odd")
    override = {
        "trade": "a#0", "year": 2031, "round": 1, "from": "SAC", "asset": "custom",
        "create": {"kind": "conditional", "originals": ["SAC"], "description": "manual"},
    }  # fmt: skip
    ledger = build_ledger([t], range(2031, 2032), {("a#0", 2031, 1, "SAC"): override})
    assert ledger.assets["custom"].owner == "SAS"
    assert ledger.review == []


def test_initial_ledger_has_every_team_pick():
    ledger = Ledger.initial(range(2027, 2034))
    assert len(ledger.assets) == 30 * 7 * 2
