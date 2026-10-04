"""OpenAI-compatible client. Same code against vLLM or Ollama.

Reads documents, nothing else. Thresholds live in domain/criteria.py. Failures
raise LLMUnavailable and there is no fallback response.

Extraction asks the server for structured output: vLLM and Ollama both accept an
OpenAI-style `response_format` with a JSON schema and constrain decoding to it.
The reply is still validated against the same schema here, because a server can
ignore the request and a constrained decoder can still emit a wrong value.
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
    # vLLM started with --api-key, or any gateway in front of it, rejects calls
    # without a bearer token. Read from LLM_API_KEY; never logged.
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> LLMConfig:
        backend = os.getenv("LLM_BACKEND", "ollama").lower()
        key = os.getenv("LLM_API_KEY") or None
        if backend == "vllm":
            return cls(os.getenv("VLLM_URL", "http://localhost:8001/v1"),
                       os.getenv("VLLM_MODEL", "qwen-small"), api_key=key)
        return cls(os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
                   os.getenv("OLLAMA_MODEL", "phi4-mini"), api_key=key)


@dataclass
class Completion:
    text: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    backend: str
    model: str


def complete(prompt: str, cfg: LLMConfig | None = None, max_tokens: int = 256,
             temperature: float = 0.0, json_schema: dict | None = None) -> Completion:
    cfg = cfg or LLMConfig.from_env()
    request: dict = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_schema is not None:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "extraction", "strict": True, "schema": json_schema},
        }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    req = urllib.request.Request(f"{cfg.base_url.rstrip('/')}/chat/completions",
                                 data=json.dumps(request).encode(),
                                 headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            payload = json.load(resp)
    except Exception as exc:
        raise LLMUnavailable(f"{cfg.base_url} ({cfg.model}): {exc}") from exc
    ms = int((time.perf_counter() - t0) * 1000)

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"malformed response from {cfg.base_url}: {payload}") from exc
    if not isinstance(text, str):
        # a refusal or a tool call arrives with no text content
        raise LLMUnavailable(f"no text content from {cfg.base_url}: {payload}")

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


EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "setback_m": {"type": ["number", "null"]},
        "height_m": {"type": ["number", "null"]},
        "coverage_pct": {"type": ["number", "null"]},
        "flood_zone_3": {"type": "boolean"},
        "listed_building": {"type": "boolean"},
    },
    "required": ["setback_m", "height_m", "coverage_pct", "flood_zone_3", "listed_building"],
    "additionalProperties": False,
}


def validate_facts(facts: object) -> dict:
    """Check extracted facts against EXTRACTION_SCHEMA. Raises LLMUnavailable.

    Hand-written rather than a JSON Schema library: five fields, and every
    failure has to be a hard stop with a message an operator can act on.
    """
    if not isinstance(facts, dict):
        raise LLMUnavailable(f"extraction is not an object: {facts!r}"[:200])
    expected = set(EXTRACTION_SCHEMA["required"])
    if set(facts) != expected:
        raise LLMUnavailable(f"extraction keys {sorted(facts)} != {sorted(expected)}")
    for key in ("setback_m", "height_m", "coverage_pct"):
        v = facts[key]
        # bool is a subclass of int in Python, and true is not a measurement
        if v is not None and (isinstance(v, bool) or not isinstance(v, int | float)):
            raise LLMUnavailable(f"{key} must be a number or null, got {v!r}")
    for key in ("flood_zone_3", "listed_building"):
        if not isinstance(facts[key], bool):
            raise LLMUnavailable(f"{key} must be true or false, got {facts[key]!r}")
    return facts


def extract_facts(narrative: str, cfg: LLMConfig | None = None) -> tuple[dict, Completion]:
    """Model reads; Python decides. Returns validated facts and the raw completion."""
    c = complete(EXTRACTION_PROMPT.format(narrative=narrative), cfg, max_tokens=200,
                 json_schema=EXTRACTION_SCHEMA)
    raw = c.text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise LLMUnavailable(f"no JSON object in model output: {raw[:200]!r}")
    try:
        facts = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"unparseable JSON from model: {raw[start:end+1][:200]!r}") from exc
    return validate_facts(facts), c
