# ADR-0008: Measure extraction reliability; keep it off the decision path

**Status:** Accepted
**From a measurement.**

## Context
`verify_llm.py` originally asserted that vLLM (Qwen2.5-0.5B) and Ollama (phi4-mini)
would extract the same facts from the same narrative. First run, they did, check
passed, moved on.

A later run, same prompt, same `temperature=0.0`, the 0.5B model returned
`setback_m: null` for a narrative that says "set back 1.4 m from the boundary". The
assertion failed.

So I ran it properly, five times per backend:

```
vLLM  (GPU, Qwen2.5-0.5B)   0/5 fully correct, 850ms avg
    setback_m      0/5
    height_m       5/5
    coverage_pct   5/5
Ollama (host, phi4-mini)    5/5 fully correct, 4539ms avg
    setback_m      5/5
```

`0/5` is the number to look at. It is not flakiness, it is a reliable failure on one
field. The 0.5B model consistently cannot pull a measurement phrased as "set back
1.4 m from the boundary" while handling "height is 3.2 m" and "coverage will be 38%"
without trouble. No sampling setting fixes a capability gap.

Two related things, since they come up:

* `temperature=0.0` is not determinism. Continuous batching changes the reduction
  order and floating-point addition is not associative, so identical requests can
  produce different logits depending on what else is in the batch.
* The single passing run told us nothing. The first version of this check passed and
  was measuring nothing.

## Decision
1. Verification measures per-field extraction reliability over N runs instead of
   asserting agreement once.
2. The decision path is invariant to that unreliability. Python evaluates the
   original text, and all five criteria resolve correctly while the extraction sits
   at 0/5 on a field.

## Consequences
* Model choice is now evidenced. 0.5B is fine for summarising and not fine for fact
  extraction on this phrasing, and there is a number behind that.
* Extraction is for enrichment and cross-checking, never an input to a threshold
  comparison (ADR-0006).
* Two backends disagreeing is a signal to put a human on the case.
* Same shape as a release gate that never fails (ADR-0007,
  `adjudication/eval/test_gate_can_fail.py`): a check that only ever passes cannot
  be distinguished from a check that is not running.
