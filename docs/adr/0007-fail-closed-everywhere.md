# ADR-0007: Fail closed. No fallbacks anywhere.

**Status:** Accepted

## Context
The reflex defensive move is a fallback: model call fails, return a default. That
is how an eval harness ends up reporting near-perfect scores while every
underlying model call is failing. The fallback answers get scored as if they were
real and nothing errors.

## Decision
No fallback paths.

* `adjudication/runtime/llm.py` raises `LLMUnavailable` on any backend failure,
  malformed response or unparseable JSON. Nothing downstream catches it.
* `adjudication/eval/run_eval.py` scores an exception as zero rather than
  skipping the case. A case that crashes is not a case that passed.
* `check_output` fails a phantom citation instead of stripping it. Stripping
  gives you a fluent answer whose evidence has quietly gone.

## Consequences
* Louder failures. Intended.
* The release gate can block on infrastructure problems. Also intended; a gate
  that cannot see infrastructure problems is not measuring the system.

## Related
`adjudication/eval/test_gate_can_fail.py` mutation-tests the gate itself.
