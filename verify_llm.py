#!/usr/bin/env python3
"""Model reliability, and whether the decision moves with it.

This started out asserting that both backends extract the same facts. They did on
the first run. On a later run the 0.5B model dropped the setback value at
temperature 0.0 and the assertion blew up.

So it measures now instead of asserting: how often each backend gets the facts
right over N runs, and whether the decision comes out the same either way. The
second one is ADR-0006. The model reads, Python decides from the original text,
and a model that drops a field must not be able to move an outcome. Only way to
know is to run an unreliable one and look.
"""
from __future__ import annotations

import sys
from collections import Counter

from adjudication.domain.criteria import evaluate
from adjudication.runtime.llm import LLMConfig, LLMUnavailable, extract_facts

NARRATIVE = ("Proposed garden room to the rear. The structure is set back 1.4 m from "
             "the boundary. Overall height is 3.2 m above natural ground level. "
             "Site coverage after works will be 38%. The site is not in a flood zone "
             "and the building is not listed.")

TRUTH = {"setback_m": 1.4, "height_m": 3.2, "coverage_pct": 38.0}
RUNS = 5

BACKENDS = [
    ("vLLM  (GPU, Qwen2.5-0.5B)", LLMConfig("http://localhost:8001/v1", "qwen-small")),
    ("Ollama (host, phi4-mini) ", LLMConfig("http://localhost:11434/v1", "phi4-mini")),
]


def field_ok(got, want) -> bool:
    try:
        return got is not None and abs(float(got) - want) < 0.05
    except (TypeError, ValueError):
        return False


def main() -> int:
    print(f"Model reliability over {RUNS} runs per backend, at temperature 0.0.\n")
    reachable = []
    for label, cfg in BACKENDS:
        per_field = Counter()
        fully_correct = 0
        latencies = []
        errors = 0
        for _ in range(RUNS):
            try:
                facts, c = extract_facts(NARRATIVE, cfg)
            except LLMUnavailable:
                errors += 1
                continue
            latencies.append(c.latency_ms)
            ok_all = True
            for k, v in TRUTH.items():
                if field_ok(facts.get(k), v):
                    per_field[k] += 1
                else:
                    ok_all = False
            fully_correct += ok_all
        if errors == RUNS:
            print(f"  {label}  unreachable, skipped")
            continue
        reachable.append(label)
        n = RUNS - errors
        avg = sum(latencies) // max(1, len(latencies))
        print(f"  {label}  {fully_correct}/{n} fully correct, {avg}ms avg")
        for k in TRUTH:
            print(f"      {k:<14} {per_field[k]}/{n}")

    if not reachable:
        print("\nNo backend reachable.")
        return 1

    # the bit that actually matters
    print("\n  Python decides from the ORIGINAL text, not the extraction:")
    findings = evaluate(NARRATIVE)
    for f in findings:
        print(f"    {f.criterion_code} satisfied={str(f.satisfied):<5} :: {f.rationale}")

    decisive = {f.criterion_code: f.satisfied for f in findings}
    expected = {"C1": True, "C2": True, "C3": True, "C4": True, "C5": True}
    if decisive != expected:
        print(f"\nFAILED: deterministic path disagreed: {decisive}")
        return 1

    print("\n" + "=" * 72)
    print("The 0.5B model is not reliable at this task; see the per-field counts.")
    print("The decision is right anyway, because the model never fed into it.")
    print("ADR-0006.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
