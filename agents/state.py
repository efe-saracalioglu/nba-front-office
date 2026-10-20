from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class FrontOfficeState(TypedDict, total=False):
    request: str
    team: str | None
    trade_date: str
    route: str
    player: str | None
    goal: dict[str, Any]
    candidates: list[dict[str, Any]]
    sql_attempts: list[dict[str, Any]]
    valuations: dict[str, dict[str, Any]]
    scouting: dict[str, dict[str, Any]]
    proposals: list[dict[str, Any]]
    target_outcomes: dict[str, str]
    critiques: list[dict[str, Any]]
    revisions: int
    approval: dict[str, Any] | None
    memo: str
    answer: str
    error: str | None
    usage: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[str], operator.add]
