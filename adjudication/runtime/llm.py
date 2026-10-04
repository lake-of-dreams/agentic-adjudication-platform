"""OpenAI-compatible client. Same code against vLLM or Ollama.

Reads documents, nothing else. Thresholds live in domain/criteria.py. Failures
raise LLMUnavailable and there is no fallback response.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass


class LLMUnavailable(RuntimeError):
    """Any backend failure. Nothing downstream catches it."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    timeout: int = 120

    @classmethod
    def from_env(cls) -> LLMConfig:
        backend = os.getenv("LLM_BACKEND", "ollama").lower()
        if backend == "vllm":
            return cls(os.getenv("VLLM_URL", "http://localhost:8001/v1"),
                       os.getenv("VLLM_MODEL", "qwen-small"))
        return cls(os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
                   os.getenv("OLLAMA_MODEL", "phi4-mini"))


@dataclass
class Completion:
    text: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    backend: str
    model: str


def complete(prompt: str, cfg: LLMConfig | None = None, max_tokens: int = 256,
             temperature: float = 0.0) -> Completion:
    cfg = cfg or LLMConfig.from_env()
    body = json.dumps({
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(f"{cfg.base_url.rstrip('/')}/chat/completions",
                                 data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            payload = json.load(resp)
    except Exception as exc:
        raise LLMUnavailable(f"{cfg.base_url} ({cfg.model}): {exc}") from exc
    ms = int((time.perf_counter() - t0) * 1000)

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMUnavailable(f"malformed response from {cfg.base_url}: {payload}") from exc

    usage = payload.get("usage") or {}
    return Completion(text.strip(), ms,
                      int(usage.get("prompt_tokens") or 0),
                      int(usage.get("completion_tokens") or 0),
                      cfg.base_url, cfg.model)


EXTRACTION_PROMPT = """You are reading a permit application. Extract ONLY what is \
explicitly stated. Do not infer, do not assume, do not decide anything.

Return strict JSON with these keys:
  "setback_m": number or null
  "height_m": number or null
  "coverage_pct": number or null
  "flood_zone_3": true/false
  "listed_building": true/false

Application text:
---
{narrative}
---
JSON:"""


def extract_facts(narrative: str, cfg: LLMConfig | None = None) -> tuple[dict, Completion]:
    """Model reads; Python decides. Returns parsed facts and the raw completion."""
    c = complete(EXTRACTION_PROMPT.format(narrative=narrative), cfg, max_tokens=200)
    raw = c.text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise LLMUnavailable(f"no JSON object in model output: {raw[:200]!r}")
    try:
        return json.loads(raw[start:end + 1]), c
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"unparseable JSON from model: {raw[start:end+1][:200]!r}") from exc
