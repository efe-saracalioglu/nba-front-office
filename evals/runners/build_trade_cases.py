from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date
from pathlib import Path

from rules.engine import validate_trade
from rules.models import Player, Trade, TradeLeg, TradeVerdict
from rules.state import LeagueState, load_league

OUT = Path(__file__).resolve().parents[1] / "nba_bench" / "trades.jsonl"
TRADE_DATE = date(2026, 11, 1)
QUOTAS = {
    "VALID": 42,
    "SALARY_MATCHING": 10,
    "SALARY_MATCHING_APRON": 10,
    "ABSORB_WITHOUT_ROOM": 5,
    "SECOND_APRON_AGGREGATION": 5,
    "SECOND_APRON_CASH": 3,
    "ROSTER_MAX": 6,
    "STEPIEN": 6,
    "RECENTLY_SIGNED": 6,
    "CASH_LIMIT": 4,
    "PICK_NOT_OWNED": 3,
}


class Proposer:
    def __init__(self, lg: LeagueState, rng: random.Random):
        self.lg, self.rng = lg, rng
        self.teams = sorted(lg.teams)

    def _salaried(self, team: str, signed_after: date | None = None) -> list[Player]:
        players = [p for p in self.lg.teams[team].players if not p.is_two_way and p.salary]
        if signed_after:
            players = [p for p in players if p.signed_on and p.signed_on >= signed_after]
        return players

    def _pair(self) -> tuple[str, str]:
        a, b = self.rng.sample(self.teams, 2)
        return a, b

    def _close_salary(self, team: str, target: int, lo: float, hi: float) -> Player | None:
        pool = [p for p in self._salaried(team) if lo * target <= p.salary <= hi * target]
        return self.rng.choice(pool) if pool else None

    def _own_firsts(self, team: str) -> list[str]:
        return sorted(a.asset_id for a in self.lg.picks.values()
                      if a.owner == team and a.round == 1 and a.counts_as_pick)  # fmt: skip

    def _seconds(self, team: str) -> list[str]:
        return sorted(
            a.asset_id for a in self.lg.picks.values() if a.owner == team and a.round == 2
        )

    def one_for_one(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        pa = self.rng.choice(self._salaried(a))
        lo, hi = self.rng.choice([(0.85, 1.15), (0.9, 1.0), (1.05, 1.6), (1.6, 3.0), (0.4, 0.8)])
        pb = self._close_salary(b, pa.salary, lo, hi)
        if not pb:
            return None
        return [TradeLeg(from_team=a, to_team=b, players=[pa.player_id]),
                TradeLeg(from_team=b, to_team=a, players=[pb.player_id])]  # fmt: skip

    def two_for_one(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        pool = self._salaried(a)
        if len(pool) < 2:
            return None
        x, y = self.rng.sample(pool, 2)
        pb = self._close_salary(b, x.salary + y.salary, 0.75, 1.3)
        if not pb:
            return None
        return [TradeLeg(from_team=a, to_team=b, players=[x.player_id, y.player_id]),
                TradeLeg(from_team=b, to_team=a, players=[pb.player_id])]  # fmt: skip

    def player_for_pick(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        pa = self.rng.choice(self._salaried(a))
        seconds = self._seconds(b)
        if not seconds:
            return None
        return [TradeLeg(from_team=a, to_team=b, players=[pa.player_id]),
                TradeLeg(from_team=b, to_team=a, picks=[self.rng.choice(seconds)])]  # fmt: skip

    def firsts_for_player(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        firsts = self._own_firsts(a)
        if len(firsts) < 2:
            return None
        start = self.rng.randrange(len(firsts) - 1)
        chosen = firsts[start : start + 2] if self.rng.random() < 0.5 else firsts[start::2][:2]
        pa = self.rng.choice(self._salaried(a))
        pb = self._close_salary(b, pa.salary, 0.9, 1.1)
        if not pb:
            return None
        return [TradeLeg(from_team=a, to_team=b, players=[pa.player_id], picks=chosen),
                TradeLeg(from_team=b, to_team=a, players=[pb.player_id])]  # fmt: skip

    def recent_signee(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        pool = self._salaried(a, signed_after=date(2026, 7, 1))
        if not pool:
            return None
        pa = self.rng.choice(pool)
        pb = self._close_salary(b, pa.salary, 0.9, 1.1)
        if not pb:
            return None
        return [TradeLeg(from_team=a, to_team=b, players=[pa.player_id]),
                TradeLeg(from_team=b, to_team=a, players=[pb.player_id])]  # fmt: skip

    def with_cash(self) -> list[TradeLeg] | None:
        legs = self.one_for_one()
        if not legs:
            return None
        cash = self.rng.choice([1_000_000, 3_000_000, 8_000_000, 9_500_000])
        legs[0] = legs[0].model_copy(update={"cash": cash})
        return legs

    def stolen_pick(self) -> list[TradeLeg] | None:
        a, b = self._pair()
        others = [
            x.asset_id for x in self.lg.picks.values() if x.owner not in (a, b) and x.round == 2
        ]
        pa = self.rng.choice(self._salaried(b))
        return [TradeLeg(from_team=a, to_team=b, picks=[self.rng.choice(others)]),
                TradeLeg(from_team=b, to_team=a, players=[pa.player_id])]  # fmt: skip

    def shapes(self):
        return [
            (self.one_for_one, 5), (self.two_for_one, 3), (self.player_for_pick, 2),
            (self.firsts_for_player, 2), (self.recent_signee, 1), (self.with_cash, 1),
            (self.stolen_pick, 0.3),
        ]  # fmt: skip


def bucket(v: TradeVerdict) -> str:
    return "VALID" if v.valid else sorted({x.code for x in v.violations})[0]


def context(lg: LeagueState, trade: Trade) -> dict:
    s = lg.season
    teams = {}
    for t in trade.teams:
        state = lg.teams[t]
        teams[t] = {
            "payroll": state.payroll,
            "standard_contracts": state.standard_roster,
            "two_way_contracts": state.two_way_roster,
            "first_round_picks_owned_by_year": lg.first_round_holdings(t),
        }
    legs = []
    for leg in trade.legs:
        players = []
        for pid in leg.players:
            p = lg.player(pid)
            players.append({"name": p.name, "salary": p.salary, "two_way": p.is_two_way,
                            "signed_on": str(p.signed_on) if p.signed_on else None,
                            "acquired_by_trade_on": str(p.acquired_by_trade_on) if p.acquired_by_trade_on else None})  # fmt: skip
        picks = []
        for aid in leg.picks:
            a = lg.picks[aid]
            picks.append({"asset_id": aid, "year": a.year, "round": a.round, "original_team": a.original,
                          "current_owner": a.owner, "kind": a.kind})  # fmt: skip
        legs.append(
            {
                "from": leg.from_team,
                "to": leg.to_team,
                "players": players,
                "picks": picks,
                "cash": leg.cash,
            }
        )
    return {
        "trade_date": str(trade.trade_date),
        "season": {
            "salary_cap": s.salary_cap, "luxury_tax": s.luxury_tax, "first_apron": s.first_apron,
            "second_apron": s.second_apron, "matching_cushion": s.trade.matching_cushion,
            "matching_bracket": s.trade.matching_bracket, "cash_limit": s.trade.cash_limit,
            "regular_season_start": str(s.calendar.regular_season_start),
            "trade_deadline": str(s.calendar.trade_deadline),
            "offseason_signing_trade_date": str(s.signing.offseason_trade_date),
            "max_standard": s.roster.max_standard, "max_two_way": s.roster.max_two_way,
            "tradable_draft_years": [s.draft.first_tradable_year, s.draft.last_tradable_year],
        },
        "teams": teams,
        "legs": legs,
    }  # fmt: skip


def build(lg: LeagueState, seed: int, max_attempts: int = 200_000) -> list[dict]:
    rng = random.Random(seed)
    proposer = Proposer(lg, rng)
    shapes, weights = zip(*proposer.shapes(), strict=True)
    filled: Counter = Counter()
    cases, seen = [], set()
    for _ in range(max_attempts):
        if all(filled[k] >= n for k, n in QUOTAS.items()):
            break
        legs = rng.choices(shapes, weights)[0]()
        if not legs:
            continue
        trade = Trade(legs=legs, trade_date=TRADE_DATE)
        key = trade.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        verdict = validate_trade(trade, lg)
        b = bucket(verdict)
        if b not in QUOTAS or filled[b] >= QUOTAS[b]:
            continue
        filled[b] += 1
        cases.append({
            "id": f"trade-{len(cases) + 1:03d}",
            "bucket": b,
            "trade": json.loads(trade.model_dump_json()),
            "context": context(lg, trade),
            "expected": {
                "valid": verdict.valid,
                "violations": sorted({(v.code, v.team) for v in verdict.violations}),
                "max_incoming": {t.team: t.max_incoming_salary for t in verdict.teams},
            },
        })  # fmt: skip
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rule-labelled trade cases for NBA-Bench")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    lg = load_league(args.db)
    cases = build(lg, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases to {args.out}")
    print(Counter(c["bucket"] for c in cases))


if __name__ == "__main__":
    main()
