from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from data import config
from data.sources.bbref_transactions import PickTransfer, fetch_transfers

log = logging.getLogger(__name__)

SEED_DIR = config.DATA_DIR / "seed"
OVERRIDES = SEED_DIR / "pick_overrides.yaml"
PICKS_CSV = SEED_DIR / "draft_picks.csv"
REVIEW_CSV = SEED_DIR / "pick_review.csv"
FIRST_TRANSACTION_SEASON = 2020


SIMPLE = re.compile(r"([A-Z]{3})(?:'s)? own\b[\s,.]*(.*)$")
POOL = re.compile(r"of ([A-Z]{3}(?:(?:,? and |, |/)[A-Z]{3})+)")


def bbref_abbr_to_nba(abbr: str) -> str:
    return config.TEAMS[config.BBREF_TO_TEAM_ID[abbr]][0]


def classify(annotation: str | None) -> tuple[str, str | None, str | None]:
    if annotation is None:
        return "none", None, None
    low = annotation.lower()
    if "swap" in low:
        return "swap", None, None
    if "favorable" in low or "one of" in low:
        return "conditional", None, None
    m = SIMPLE.match(annotation)
    if m:
        rest = m.group(2).strip() or None
        return "simple", m.group(1), rest
    if "protect" in low:
        return "simple_unknown_original", None, annotation
    return "unknown", None, None


def pool(annotation: str | None) -> list[str]:
    m = POOL.search(annotation or "")
    if not m:
        return []
    teams = re.findall(r"[A-Z]{3}", m.group(1))
    return [t for t in teams if t in config.BBREF_TO_TEAM_ID]


@dataclass
class Asset:
    asset_id: str
    year: int
    round: int
    owner: str
    kind: str
    originals: list[str]
    description: str = ""
    protection: str | None = None
    last_trade: str | None = None
    inferred: bool = False


@dataclass
class Ledger:
    years: range
    assets: dict[str, Asset] = field(default_factory=dict)
    review: list[dict] = field(default_factory=list)

    @classmethod
    def initial(cls, years: range) -> Ledger:
        ledger = cls(years)
        for abbr in config.BBREF_TO_TEAM_ID:
            for y in years:
                for r in (1, 2):
                    aid = f"{y}-{r}-{abbr}"
                    ledger.assets[aid] = Asset(aid, y, r, abbr, "own", [abbr], f"{abbr} own")
        return ledger

    def _flag(self, t: PickTransfer, reason: str) -> None:
        self.review.append(
            {
                "trade": t.trade_key, "year": t.year, "round": t.round,
                "from": t.from_team, "to": t.to_team, "reason": reason,
                "annotation": t.annotation, "text": t.text,
            }
        )  # fmt: skip

    def _move(self, aid: str, t: PickTransfer, inferred: bool = False) -> None:
        asset = self.assets[aid]
        if asset.owner != t.from_team:
            self._flag(t, f"conflict: {aid} owned by {asset.owner}, not {t.from_team}")
        asset.owner = t.to_team
        asset.last_trade = t.trade_key
        asset.inferred = asset.inferred or inferred
        if asset.kind == "own":
            asset.kind = "acquired"

    def _held(self, t: PickTransfer, kinds: tuple[str, ...]) -> list[Asset]:
        held = [
            a for a in self.assets.values()
            if a.year == t.year and a.round == t.round and a.owner == t.from_team
            and a.kind in kinds
        ]  # fmt: skip
        return sorted(held, key=lambda a: a.last_trade or "", reverse=True)

    def _create(self, t: PickTransfer, kind: str, originals: list[str], desc: str) -> str:
        aid = f"{t.year}-{t.round}-{kind}-{t.trade_key}-{t.from_team}"
        self.assets[aid] = Asset(aid, t.year, t.round, t.from_team, kind, originals, desc)
        return aid

    def apply(self, t: PickTransfer, override: dict | None) -> None:
        if t.year not in self.years:
            return
        if override:
            self._apply_override(t, override)
            return
        kind, original, protection = classify(t.annotation)

        if kind == "simple":
            aid = f"{t.year}-{t.round}-{original}"
            if protection is None and t.note and t.picks_in_trade == 1:
                protection = t.note
            elif t.note and t.picks_in_trade > 1:
                self._flag(t, "loose protection note in a multi-pick trade")
            self._move(aid, t)
            if protection:
                self.assets[aid].protection = protection
            return

        if kind in ("swap", "conditional"):
            asset_kind = "swap_right" if kind == "swap" else "conditional"
            held = self._held(t, (asset_kind,))
            if held:
                self._move(held[0].asset_id, t)
                return
            originals = pool(t.annotation) or [t.from_team]
            aid = self._create(t, asset_kind, originals, t.annotation or "")
            self._move(aid, t)
            return

        if kind == "simple_unknown_original":
            own = f"{t.year}-{t.round}-{t.from_team}"
            if self.assets[own].owner == t.from_team:
                self._move(own, t, inferred=True)
                self.assets[own].protection = protection
            else:
                self._flag(t, "protected pick of unknown origin")
            return

        if kind == "none":
            own = f"{t.year}-{t.round}-{t.from_team}"
            if self.assets[own].owner == t.from_team:
                self._move(own, t, inferred=True)
                return
            held = self._held(t, ("acquired", "conditional", "swap_right"))
            if len(held) == 1:
                self._move(held[0].asset_id, t, inferred=True)
                return
            self._flag(t, f"unannotated pick; giver holds {len(held)} candidate assets")
            return

        self._flag(t, f"unrecognized annotation: {t.annotation}")

    def _apply_override(self, t: PickTransfer, override: dict) -> None:
        if "skip" in override:
            return
        aid = override["asset"]
        if "create" in override:
            spec = override["create"]
            self.assets[aid] = Asset(
                aid, t.year, t.round, t.from_team, spec["kind"], spec["originals"],
                spec.get("description", ""), spec.get("protection"),
            )  # fmt: skip
        if aid not in self.assets:
            self._flag(t, f"override refers to unknown asset {aid}")
            return
        self._move(aid, t)

    def frame(self) -> pd.DataFrame:
        rows = []
        for a in self.assets.values():
            rows.append(
                {
                    "asset_id": a.asset_id, "year": a.year, "round": a.round,
                    "owner_team_id": config.BBREF_TO_TEAM_ID[a.owner],
                    "original_team_id": (
                        config.BBREF_TO_TEAM_ID[a.originals[0]] if len(a.originals) == 1 else None
                    ),
                    "original_teams": ",".join(bbref_abbr_to_nba(o) for o in a.originals),
                    "kind": a.kind, "description": a.description,
                    "protection": a.protection, "last_trade": a.last_trade,
                    "inferred": a.inferred,
                }
            )  # fmt: skip
        df = pd.DataFrame(rows)
        df["original_team_id"] = df["original_team_id"].astype("Int64")
        return df.sort_values(["year", "round", "asset_id"]).reset_index(drop=True)


def load_overrides(path: Path = OVERRIDES) -> dict[tuple, dict]:
    if not path.exists():
        return {}
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {(e["trade"], e["year"], e["round"], e["from"]): e for e in entries}


def build_ledger(
    transfers: list[PickTransfer], years: range, overrides: dict[tuple, dict]
) -> Ledger:
    ledger = Ledger.initial(years)
    for t in transfers:
        ledger.apply(t, overrides.get((t.trade_key, t.year, t.round, t.from_team)))
    return ledger


def draft_window() -> range:
    first = config.season_end_year(config.CURRENT_SEASON)
    return range(first, first + 7)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild future draft pick ownership")
    parser.add_argument("--refresh", action="store_true", help="re-download transaction pages")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    last_page = config.season_end_year(config.CURRENT_SEASON)
    transfers = fetch_transfers(FIRST_TRANSACTION_SEASON, last_page, args.refresh)
    ledger = build_ledger(transfers, draft_window(), load_overrides())
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    ledger.frame().to_csv(PICKS_CSV, index=False)
    pd.DataFrame(
        ledger.review,
        columns=["trade", "year", "round", "from", "to", "reason", "annotation", "text"],
    ).to_csv(REVIEW_CSV, index=False)
    log.info(
        "%d assets, %d transfers applied window %s; %d items to review -> %s",
        len(ledger.assets), len(transfers), list(draft_window()), len(ledger.review), REVIEW_CSV,
    )  # fmt: skip


if __name__ == "__main__":
    main()
