from __future__ import annotations

import json

from pydantic import BaseModel, Field

from agents import tracing
from agents.llm import LLM

DIMENSIONS = ["goal_fit", "realism", "grounding", "risk_awareness", "overall"]

RUBRIC = """You are grading an NBA front-office assistant's reply to a team owner. Score each dimension 1-5.

goal_fit: do the recommended trades address the stated need and respect every constraint (positions, payroll line, protected picks, untouchable players)? If no trade is recommended, is that justified by the constraints?
realism: would the other teams plausibly accept? Lopsided trades (a star for role players) score 1-2.
grounding: are names, salaries, projections and payroll figures consistent with the verified facts? Any invented statistic, wrong number or claim that contradicts the facts lowers this score.
risk_awareness: does the reply name the real risks (age, injury, value lost, hard caps, roster spots, uncertainty)?
overall: how useful is this reply to a real general manager?

5 = excellent, 3 = acceptable with clear flaws, 1 = harmful or wrong.
The verified facts come from a rules engine, a valuation model and the database. Trust them over the reply."""


class Scores(BaseModel):
    goal_fit: int = Field(ge=1, le=5)
    realism: int = Field(ge=1, le=5)
    grounding: int = Field(ge=1, le=5)
    risk_awareness: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    rationale: str


def judge(scenario: dict, reply: str, checked: list[dict], llm: LLM | None = None) -> dict:
    llm = llm or LLM()
    facts = [
        {
            "proposal": i + 1,
            "legal": c["legal"],
            "rule_violations": c["violations"],
            "failed_checks": c["failed_checks"],
            "incoming_players_true_facts": c.get("incoming"),
            "value_balance": c.get("value"),
            "our_payroll_before_after": c.get("payroll_before_after"),
        }
        for i, c in enumerate(checked)
    ]
    user = (
        f"Owner's team: {scenario['team']}\nOwner's request: {scenario['request']}\n"
        f"Constraints to check: {json.dumps(scenario['checks'])}\n\n"
        f"Verified facts about each proposed trade:\n{json.dumps(facts, default=str)}\n\n"
        f"Assistant's reply:\n<reply>\n{reply or '(empty)'}\n</reply>"
    )
    scores = llm.structured("judge", RUBRIC, user, Scores)
    return scores.model_dump() | {"judge_model": llm.model_for("judge"), "judge_usage": llm.usage()}


def attach_scores(trace_id: str | None, scores: dict, prefix: str = "judge") -> None:
    lf = tracing.client()
    if lf is None or not trace_id:
        return
    for d in DIMENSIONS:
        lf.create_score(
            trace_id=trace_id,
            name=f"{prefix}.{d}",
            value=float(scores[d]),
            comment=scores.get("rationale") if d == "overall" else None,
        )
    lf.flush()
