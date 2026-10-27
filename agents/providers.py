from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

OPENAI_COMPATIBLE = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
}
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")
OLLAMA_URL = os.environ.get("OLLAMA_URL") or (
    "https://ollama.com" if OLLAMA_API_KEY else "http://localhost:11434"
)

MAX_OUTPUT_TOKENS = 8192


def ollama_request(model: str) -> tuple[str, dict]:
    if OLLAMA_API_KEY and "ollama.com" in OLLAMA_URL:
        return model.removesuffix("-cloud"), {"Authorization": f"Bearer {OLLAMA_API_KEY}"}
    return model, {}


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    seconds: float


def _ollama(model: str, system: str, user: str, json_mode: bool, timeout: float) -> LLMResult:
    model, headers = ollama_request(model)
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": MAX_OUTPUT_TOKENS},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["format"] = "json"
    start = time.perf_counter()
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout, headers=headers)
    r.raise_for_status()
    d = r.json()
    return LLMResult(
        d["message"]["content"],
        d.get("prompt_eval_count", 0),
        d.get("eval_count", 0),
        time.perf_counter() - start,
    )


def _openai_compatible(
    provider: str, model: str, system: str, user: str, json_mode: bool, timeout: float
) -> LLMResult:
    base, key_env = OPENAI_COMPATIBLE[provider]
    key = os.environ.get(key_env)
    if not key:
        raise RuntimeError(f"{key_env} is not set; add it to .env to use {provider}")
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    start = time.perf_counter()
    for attempt in range(6):
        r = httpx.post(
            f"{base}/chat/completions",
            json=body,
            timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
        )
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("retry-after", 2**attempt * 5)))
    r.raise_for_status()
    d = r.json()
    usage = d.get("usage", {})
    return LLMResult(
        d["choices"][0]["message"]["content"],
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        time.perf_counter() - start,
    )


def chat(
    spec: str, system: str, user: str, json_mode: bool = True, timeout: float = 300
) -> LLMResult:
    provider, _, model = spec.partition(":")
    if provider == "ollama":
        return _ollama(model, system, user, json_mode, timeout)
    if provider in OPENAI_COMPATIBLE:
        return _openai_compatible(provider, model, system, user, json_mode, timeout)
    raise ValueError(f"unknown provider in {spec!r}; use ollama:, groq:, openrouter: or gemini:")
