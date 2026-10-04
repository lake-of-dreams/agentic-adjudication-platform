.PHONY: install test lint demo gate mutate redteam compare llm all

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

demo:
	.venv/bin/python run_demo.py

gate:
	.venv/bin/python adjudication/eval/run_eval.py

mutate:
	.venv/bin/python adjudication/eval/test_gate_can_fail.py

redteam:
	.venv/bin/python adjudication/redteam/suite.py

compare:
	.venv/bin/python compare.py

# Needs a live backend on :8001 (vLLM) or :11434 (Ollama).
llm:
	.venv/bin/python verify_llm.py

all: lint test gate mutate redteam compare
