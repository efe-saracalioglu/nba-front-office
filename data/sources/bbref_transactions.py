from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

from data.sources.bbref import fetch_html

PICK = re.compile(r"\ba (\d{4}) (1st|2nd) round draft pick\b")
_ANN_HEAD = r"\d{4} (?:[\w-]+ ){0,3}?(?:1st|2nd)-rd (?:draft )?pick (?:is|was)"
ANNOTATION = re.compile(
    r"(\d{4}) (?:[\w-]+ ){0,3}?(1st|2nd)-rd (?:draft )?pick (?:is|was) (.*?)"
    rf"(?=\s*\(?{_ANN_HEAD}|\s+\d{{4}} (?:[\w-]+ ){{0,3}}?(?:1st|2nd)-rd\b"
    r"|\s+[A-Z][a-z]+(?: [A-Z][a-z]+)* received|$)"
)
SIMPLE = re.compile(r"([A-Z]{3})(?:'s)? own\b")
COMPLEX_WORDS = re.compile(
    r"swap|favorable|conditional|convey|protect|one of|optioned|forfeit|originally", re.I
)
LEG = re.compile(r"<F:(\w{3})> traded (.*?) to the <T:(\w{3})>(?: for (.*))?$")


@dataclass
class PickTransfer:
    trade_key: str
    date: date
    year: int
    round: int
    from_team: str
    to_team: str
    original_team: str | None
    annotation: str | None
    complex: bool
    text: str
    note: str | None = None
    picks_in_trade: int = 1


def _marked_text(p) -> str:
    p = BeautifulSoup(str(p), "lxml").p
    for a in p.find_all("a"):
        if a.get("data-attr-from"):
            a.replace_with(f"<F:{a['data-attr-from']}>")
        elif a.get("data-attr-to"):
            a.replace_with(f"<T:{a['data-attr-to']}>")
    return " ".join(p.get_text(" ").split())


def _legs(main: str) -> list[tuple[str, str, str]]:
    legs = []
    for segment in re.split(r";(?: and)?", main):
        m = LEG.search(segment.strip().rstrip(".").strip())
        if not m:
            continue
        giver, items, receiver, back = m.groups()
        legs.append((giver, receiver, items))
        if back:
            legs.append((receiver, giver, back))
    return legs


def parse_trade(text_marked: str, plain: str, trade_key: str, day: date) -> list[PickTransfer]:
    first_ann = re.search(_ANN_HEAD, text_marked)
    main = text_marked[: first_ann.start()] if first_ann else text_marked
    tail = text_marked[first_ann.start() :] if first_ann else ""
    pending: dict[tuple[int, int], list[str]] = {}
    for y, r, ann in ANNOTATION.findall(tail):
        pending.setdefault((int(y), int(r[0])), []).append(ann.strip(" ()"))

    residual = " ".join(ANNOTATION.sub("", tail).split())
    loose_protection = "protect" in residual.lower()
    legs = _legs(main)
    n_picks = sum(len(PICK.findall(items)) for _, _, items in legs)

    out = []
    for giver, receiver, items in legs:
        for y, r in PICK.findall(items):
            key = (int(y), int(r[0]))
            ann = pending[key].pop(0) if pending.get(key) else None
            simple = SIMPLE.match(ann) if ann else None
            is_complex = loose_protection or (
                ann is not None and (not simple or bool(COMPLEX_WORDS.search(ann)))
            )
            out.append(
                PickTransfer(
                    trade_key=trade_key,
                    date=day,
                    year=key[0],
                    round=key[1],
                    from_team=giver,
                    to_team=receiver,
                    original_team=simple.group(1) if simple and not is_complex else None,
                    annotation=ann,
                    complex=is_complex,
                    text=plain,
                    note=residual if loose_protection else None,
                    picks_in_trade=n_picks,
                )
            )
    return out


def parse_page(html: str) -> list[PickTransfer]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.find("ul", class_="page_index").find_all("li", recursive=False):
        day = datetime.strptime(li.span.get_text(strip=True), "%B %d, %Y").date()
        for i, p in enumerate(li.find_all("p")):
            plain = " ".join(p.get_text(" ").split())
            if " traded " not in plain or "draft pick" not in plain:
                continue
            out.extend(parse_trade(_marked_text(p), plain, f"{day.isoformat()}#{i}", day))
    return out


def fetch_transfers(first_year: int, last_year: int, refresh: bool = False) -> list[PickTransfer]:
    out = []
    for y in range(first_year, last_year + 1):
        html = fetch_html(f"/leagues/NBA_{y}_transactions.html", f"transactions_{y}.html", refresh)
        out.extend(parse_page(html))
    return sorted(out, key=lambda t: (t.date, t.trade_key))
