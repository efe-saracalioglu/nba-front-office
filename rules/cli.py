from __future__ import annotations

import argparse
import re
import sys
from datetime import date

from rules.engine import validate_trade
from rules.models import Trade, TradeLeg, TradeVerdict
from rules.state import LeagueState, load_league

LEG = re.compile(r"^(?P<frm>[A-Z]{3})>(?P<to>[A-Z]{3}):(?P<items>.+)$")
PICK = re.compile(r"^\d{4}-[12]-")


def parse_leg(text: str, lg: LeagueState) -> TradeLeg:
    m = LEG.match(text.strip())
    if not m:
        raise ValueError(
            f"bad leg {text!r}; expected FROM>TO:item,item (e.g. DEN>GSW:Nikola Jokić,2029-1-DEN,cash=2000000)"
        )
    players, picks, cash = [], [], 0
    for item in (x.strip() for x in m["items"].split(",") if x.strip()):
        if item.startswith("cash="):
            cash += int(item.removeprefix("cash=").replace("_", ""))
        elif PICK.match(item):
            picks.append(item)
        else:
            player = lg.find_player(item, m["frm"])
            if player is None:
                raise ValueError(f"no player named {item!r} on {m['frm']}")
            players.append(player.player_id)
    return TradeLeg(from_team=m["frm"], to_team=m["to"], players=players, picks=picks, cash=cash)


def render(v: TradeVerdict) -> str:
    lines = [v.explain(), ""]
    for t in v.teams:
        lines.append(
            f"{t.team}: payroll ${t.payroll_before / 1e6:,.1f}M -> ${t.payroll_after / 1e6:,.1f}M "
            f"({t.status_before} -> {t.status_after}); out ${t.outgoing_salary / 1e6:,.2f}M, "
            f"in ${t.incoming_salary / 1e6:,.2f}M (max ${(t.max_incoming_salary or 0) / 1e6:,.2f}M); "
            f"roster {t.standard_roster_before} -> {t.standard_roster_after}"
            + (
                f"; TPE ${t.traded_player_exception / 1e6:,.2f}M"
                if t.traded_player_exception
                else ""
            )
            + (f"; hard cap: {t.hard_cap}" if t.hard_cap else "")
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a trade against the CBA rules engine")
    parser.add_argument(
        "legs", nargs="+", help='e.g. "DEN>GSW:Nikola Jokić" "GSW>DEN:Stephen Curry"'
    )
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    lg = load_league()
    try:
        trade = Trade(legs=[parse_leg(x, lg) for x in args.legs], trade_date=args.date)
    except ValueError as e:
        sys.exit(str(e))
    verdict = validate_trade(trade, lg)
    print(verdict.model_dump_json(indent=2) if args.json else render(verdict))
    sys.exit(0 if verdict.valid else 1)


if __name__ == "__main__":
    main()
