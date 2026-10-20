from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from agents.llm import LLM
from agents.toolbox import ToolBox
from data.config import ROOT

PROMPTS = Path(__file__).resolve().parent / "prompts"
MARKET_YAML = ROOT / "config" / "trade_market.yaml"


@cache
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


@cache
def market() -> dict:
    return yaml.safe_load(MARKET_YAML.read_text(encoding="utf-8"))


@dataclass
class Deps:
    llm: LLM = field(default_factory=LLM)
    tools: ToolBox = field(default_factory=ToolBox)
    devils_advocate: bool = True
    sql_self_correction: bool = True
    _usage_mark: int = 0
    _tool_mark: int = 0

    def flush(self, event: str | None = None) -> dict:
        usage = self.llm.usage()[self._usage_mark :]
        tools = self.tools.calls[self._tool_mark :]
        self._usage_mark += len(usage)
        self._tool_mark += len(tools)
        out = {"usage": usage, "tool_calls": tools}
        if event:
            out["events"] = [event]
        return out
