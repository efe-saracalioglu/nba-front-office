from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from agents.providers import chat
from agents.tracing import observation
from data.config import ROOT

MODELS_YAML = ROOT / "config" / "models.yaml"
T = TypeVar("T", bound=BaseModel)


class LLMOutputError(RuntimeError):
    pass


@cache
def _models_config(path: Path = MODELS_YAML) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass
class Call:
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    seconds: float
    attempts: int
    ok: bool


@dataclass
class LLM:
    overrides: dict[str, str] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    def model_for(self, role: str) -> str:
        cfg = _models_config()
        return self.overrides.get(role) or cfg["roles"].get(role) or cfg["default"]

    def _record(self, role: str, model: str, res, seconds: float, attempts: int, ok: bool) -> None:
        self.calls.append(Call(role, model, res.input_tokens if res else 0, res.output_tokens if res else 0,
                               round(seconds, 2), attempts, ok))  # fmt: skip

    def _chat(self, role: str, model: str, system: str, user: str, json_mode: bool = True):
        with observation(f"llm:{role}", as_type="generation", model=model,
                         input=[{"role": "system", "content": system}, {"role": "user", "content": user}]) as gen:  # fmt: skip
            res = chat(model, system, user, json_mode=json_mode)
            price = (
                _models_config()
                .get("list_prices_per_million_tokens", {})
                .get(model, {"input": 0.0, "output": 0.0})
            )
            gen.update(
                output=res.text,
                usage_details={"input": res.input_tokens, "output": res.output_tokens},
                cost_details={
                    "input": res.input_tokens * price["input"] / 1e6,
                    "output": res.output_tokens * price["output"] / 1e6,
                },
            )
            return res

    def text(self, role: str, system: str, user: str) -> str:
        model = self.model_for(role)
        start = time.perf_counter()
        res = self._chat(role, model, system, user, json_mode=False)
        self._record(role, model, res, time.perf_counter() - start, 1, True)
        return res.text.strip()

    def structured(self, role: str, system: str, user: str, schema: type[T], retries: int = 2) -> T:
        model = self.model_for(role)
        prompt = f"{user}\n\nReply with one JSON object matching this schema:\n{json.dumps(schema.model_json_schema())}"
        start, attempts, res, last_error = time.perf_counter(), 0, None, ""
        while attempts <= retries:
            attempts += 1
            res = self._chat(
                role,
                model,
                system,
                prompt
                if not last_error
                else f"{prompt}\n\nYour previous reply was invalid: {last_error}. Fix it.",
            )
            try:
                parsed = _validate(schema, _extract_json(res.text))
                self._record(role, model, res, time.perf_counter() - start, attempts, True)
                return parsed
            except (ValueError, ValidationError) as e:
                last_error = str(e).splitlines()[0][:300]
        self._record(role, model, res, time.perf_counter() - start, attempts, False)
        raise LLMOutputError(
            f"{role} returned invalid output after {attempts} attempts: {last_error}"
        )

    def usage(self) -> list[dict]:
        return [asdict(c) for c in self.calls]


def _validate(schema: type[T], data: dict) -> T:
    try:
        return schema.model_validate(data)
    except ValidationError:
        inner = data.get("properties") if isinstance(data, dict) else None
        if isinstance(inner, dict):
            return schema.model_validate(inner)
        raise


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("no JSON object in reply") from None
        return json.loads(m.group(0))


def cost_report(usage: list[dict]) -> dict:
    prices = _models_config().get("list_prices_per_million_tokens", {})
    by_role: dict[str, dict] = {}
    for u in usage:
        r = by_role.setdefault(
            u["role"],
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "usd": 0.0},
        )
        p = prices.get(u["model"], {"input": 0.0, "output": 0.0})
        r["calls"] += 1
        r["input_tokens"] += u["input_tokens"]
        r["output_tokens"] += u["output_tokens"]
        r["seconds"] = round(r["seconds"] + u["seconds"], 2)
        r["usd"] = round(
            r["usd"] + (u["input_tokens"] * p["input"] + u["output_tokens"] * p["output"]) / 1e6, 5
        )
    total = {
        k: round(sum(r[k] for r in by_role.values()), 5)
        for k in ("calls", "input_tokens", "output_tokens", "seconds", "usd")
    }
    return {"by_role": by_role, "total": total}
