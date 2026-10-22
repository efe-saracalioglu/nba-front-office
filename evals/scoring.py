from __future__ import annotations

import re

from data.crosswalk import normalize_name

_SEASON = re.compile(r"\b(?:19|20)\d{2}\s*[-–/]\s*\d{2,4}\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER = re.compile(r"\$?\s*(-?\d[\d,]*(?:\.\d+)?)\s*(million|billion|m\b|bn\b|b\b|k\b)?", re.I)
_SCALE = {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9, "k": 1e3}


def numbers(text: str) -> list[float]:
    text = _YEAR.sub(" ", _SEASON.sub(" ", text))
    out = []
    for value, unit in _NUMBER.findall(text):
        try:
            v = float(value.replace(",", ""))
        except ValueError:
            continue
        out.append(v * _SCALE.get((unit or "").lower(), 1.0))
    return out


_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def _contains(answer: str, phrase: str) -> bool:
    answer, phrase = answer.translate(_DASHES), phrase.translate(_DASHES)
    a, p = f" {normalize_name(answer)} ", f" {normalize_name(phrase)} "
    return p.strip() != "" and p in a


def check(item: dict, answer: str | None) -> tuple[bool, str]:
    if not answer:
        return False, "no answer"
    kind, gold = item["kind"], item["answer"]
    if kind in ("name", "team", "text"):
        options = [str(gold), *item.get("aliases", [])]
        ok = any(_contains(answer, o) for o in options)
        return ok, "matched" if ok else f"expected {gold}"
    question_numbers = set(numbers(item["question"]))
    found = [v for v in numbers(answer) if v not in question_numbers or v == float(gold)]
    if kind == "money":
        tol = abs(float(gold)) * item.get("tolerance_pct", 0.01)
    else:
        tol = item.get("tolerance", 0)
    ok = any(abs(v - float(gold)) <= tol + 1e-9 for v in found)
    return ok, "matched" if ok else f"expected {gold}, found {found[:6]}"
