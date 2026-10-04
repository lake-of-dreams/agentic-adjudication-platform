# Guide 4 — Runbook

## Prerequisites
* Python 3.12+ (developed on 3.14)
* Optional: Ollama on `:11434`, vLLM on `:8001`

Core runs with no GPU, no network and no external services. Only `verify_llm.py`
needs a live backend.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install langgraph pytest
```

`make install` instead if you want the editable install plus ruff.

## Commands

| Command | What it proves |
|---|---|
| `.venv/bin/python run_demo.py` | four end-to-end cases, audit reconstruction |
| `.venv/bin/python -m pytest tests/ -q` | 36 invariant tests |
| `.venv/bin/python adjudication/eval/run_eval.py` | release gate: 6 cases × 8 runs, gated on worst |
| `.venv/bin/python adjudication/eval/test_gate_can_fail.py` | the gate can actually fail |
| `.venv/bin/python adjudication/redteam/suite.py` | 10 attacks, OWASP-mapped |
| `.venv/bin/python compare.py` | supervisor vs swarm auditability |
| `.venv/bin/python verify_llm.py` | per-field extraction reliability on vLLM and Ollama |

## Serving a model

**Ollama** (usually already running):
```bash
ollama serve &
ollama pull phi4-mini
```

**vLLM** on a small GPU — see the sibling `llm-inference-platform` repo, or:
```bash
VLLM_USE_FLASHINFER_SAMPLER=0 vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --port 8001 --max-model-len 2048 --gpu-memory-utilization 0.85 \
  --max-num-seqs 16 --enforce-eager --served-model-name qwen-small
```

## Selecting a backend
```bash
LLM_BACKEND=ollama .venv/bin/python verify_llm.py   # default
LLM_BACKEND=vllm   .venv/bin/python verify_llm.py
```

## Troubleshooting

**`LLMUnavailable`** — there is no fallback, by design (ADR-0007). Check the
backend is up: `curl localhost:11434/api/tags` or `curl localhost:8001/health`.

**vLLM: `Engine core initialization failed. Failed core proc(s): {}`** — on a
small GPU this looks like OOM and usually is not. If the log shows a healthy
"Available KV cache memory" line immediately before the traceback then memory
loaded fine, so suspect the FlashInfer sampler and set
`VLLM_USE_FLASHINFER_SAMPLER=0`.

**`ModuleNotFoundError: platform.redaction`** — the runtime package is
`adjudication/runtime/`, not `platform/`, because `platform` collides with a
Python stdlib module.

## What to expect

`run_demo.py` — CASE-1 grants. CASE-2, CASE-3 and CASE-4 suspend for an officer;
CASE-3 because the input guardrail catches the suppression attempt. Audit chain
verifies over 37 entries.

`adjudication/eval/run_eval.py` — all six cases PASS at 1.00. Anything below its
tier threshold exits non-zero.
