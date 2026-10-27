from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache, wraps
from typing import Any

from dotenv import load_dotenv


class _Noop:
    def update(self, **_: Any) -> None:
        pass


@cache
def client():
    load_dotenv()
    if os.environ.get("FRONT_OFFICE_TRACING", "1") == "0":
        return None
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    from langfuse import get_client

    return get_client()


def enabled() -> bool:
    return client() is not None


@contextmanager
def observation(name: str, as_type: str = "span", **fields: Any) -> Iterator[Any]:
    lf = client()
    if lf is None:
        yield _Noop()
        return
    with lf.start_as_current_observation(name=name, as_type=as_type, **fields) as obs:
        yield obs


@contextmanager
def run_trace(
    name: str, session_id: str, tags: list[str], metadata: dict, request: str
) -> Iterator[Any]:
    lf = client()
    if lf is None:
        yield _Noop()
        return
    from langfuse import propagate_attributes

    with (
        propagate_attributes(
            session_id=session_id,
            tags=tags,
            trace_name=name,
            metadata={k: str(v) for k, v in metadata.items()},
        ),
        lf.start_as_current_observation(name=name, as_type="chain", input=request) as root,
    ):
        yield root
    lf.flush()


def traced_node(name: str, fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
    @wraps(fn)
    def wrapper(state: dict) -> dict:
        with observation(
            name,
            as_type="agent",
            input={k: state.get(k) for k in ("request", "team", "route", "goal") if state.get(k)},
        ) as obs:
            out = fn(state)
            summary = {k: v for k, v in out.items() if k not in ("usage", "tool_calls")}
            obs.update(output=summary)
            return out

    return wrapper


def current_trace_id() -> str | None:
    lf = client()
    return lf.get_current_trace_id() if lf else None
