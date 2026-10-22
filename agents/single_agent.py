from __future__ import annotations

import json
import re
import time

import anyio
import httpx
from mcp import Client

from agents import tracing
from agents.llm import LLM, Call, cost_report
from agents.providers import OLLAMA_URL, ollama_request
from agents.toolbox import ToolBox, ToolCallError

MAX_STEPS = 24
SYSTEM = """You are the general manager of an NBA team, working alone with tools.
Use the tools for every fact: rosters, salaries, draft picks, projections, news and trade legality.
Trade legality comes only from validate_trade. Never claim a trade is legal unless validate_trade said so.

For trade requests, finish with a short memo for the owner, then a fenced ```json block:
{"proposals": [{"legs": [{"from_team": "BOS", "to_team": "SAS", "players": ["Name"], "picks": ["2030-1-BOS"], "cash": 0}, ...]}]}
List at most three proposals, each one you validated. For other questions, answer in at most six sentences."""


async def _list_tools(server) -> list[dict]:
    async with Client(server) as c:
        listed = await c.list_tools()
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.input_schema}} for t in listed.tools]  # fmt: skip


def _ollama_chat(model: str, messages: list[dict], tools: list[dict]) -> dict:
    model, headers = ollama_request(model)
    body = {
        "model": model,
        "stream": False,
        "messages": messages,
        "tools": tools,
        "options": {"temperature": 0, "num_ctx": 32768},
    }
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=300, headers=headers)
    r.raise_for_status()
    return r.json()


def _truncate(data, limit: int = 6000) -> str:
    text = json.dumps(data, default=str)
    return (
        text if len(text) <= limit else text[:limit] + f"... [truncated {len(text) - limit} chars]"
    )


def extract_proposals(text: str) -> list[dict]:
    m = re.search(r"```json\s*(\{.*?\})\s*```", text or "", re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1)).get("proposals", [])
    except json.JSONDecodeError:
        return []


def run_single_agent(request: str, team: str | None, trade_date: str, tags: list[str], session: str,
                     model_role: str = "single_agent") -> dict:  # fmt: skip
    llm = LLM()
    model_spec = llm.model_for(model_role)
    model = model_spec.partition(":")[2]
    tools = ToolBox()
    schemas = anyio.run(_list_tools, tools.server)
    user = (
        request
        + (f"\nOur team: {team}." if team else "")
        + f"\nToday is {trade_date}; use it as trade_date."
    )
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    start, answer, error, steps = time.perf_counter(), "", None, 0
    with tracing.run_trace(
        "nba-bench-single-agent", session, tags, {"single_agent": model_spec}, request
    ) as root:
        try:
            while steps < MAX_STEPS:
                steps += 1
                last = steps == MAX_STEPS
                if last:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Stop calling tools. Give your final answer now, using only what the tools returned.",
                        }
                    )
                t0 = time.perf_counter()
                with tracing.observation(
                    "llm:single_agent", as_type="generation", model=model_spec, input=messages[-1]
                ) as gen:
                    reply = _ollama_chat(model, messages, [] if last else schemas)
                    msg = reply["message"]
                    gen.update(
                        output=msg,
                        usage_details={
                            "input": reply.get("prompt_eval_count", 0),
                            "output": reply.get("eval_count", 0),
                        },
                    )
                llm.calls.append(Call("single_agent", model_spec, reply.get("prompt_eval_count", 0), reply.get("eval_count", 0),
                                      round(time.perf_counter() - t0, 2), 1, True))  # fmt: skip
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content", ""),
                        "tool_calls": msg.get("tool_calls", []),
                    }
                )
                if last or not msg.get("tool_calls"):
                    answer = msg.get("content", "")
                    if not answer:
                        error = "no final answer after the step budget"
                    break
                for call in msg["tool_calls"]:
                    fn = call["function"]
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    try:
                        result = tools.call(fn["name"], **args)
                        content = _truncate(result)
                    except (ToolCallError, TypeError, ValueError) as e:
                        content = f"ERROR: {e}"
                    messages.append({"role": "tool", "content": content, "tool_name": fn["name"]})
            else:
                error = f"stopped after {MAX_STEPS} steps without a final answer"
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            error = f"{type(e).__name__}: {e}"
        trace_id = tracing.current_trace_id()
        root.update(output=answer or error)
    return {
        "answer": answer, "proposals_raw": extract_proposals(answer), "error": error, "trace_id": trace_id,
        "seconds": round(time.perf_counter() - start, 1), "cost": cost_report(llm.usage())["total"],
        "tool_calls": len(tools.calls), "steps": steps, "route": "single_agent",
    }  # fmt: skip
