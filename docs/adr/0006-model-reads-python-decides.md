# ADR-0006: The model reads. Python decides.

**Status:** Accepted

## Context
The tempting design is to let the model do the whole job: read the application,
apply the criteria, return a decision. It produces fluent, usually-correct output,
which is the trap.

Two things break. A sampled model is not reproducible, and an auditor re-performs
the threshold comparison by hand and expects it to match exactly. And threshold
arithmetic is the thing language models are worst at while sounding most certain.

## Decision
* Model reads narrative and documents, extracts stated facts, produces citations.
  `adjudication/runtime/llm.py::extract_facts`.
* Python applies every threshold. `adjudication/domain/criteria.py`.

Python evaluates the original text, not the extraction. The extraction is for
enrichment and cross-checking, never the input to a decision.

## Consequences
* Two readers of the same document can disagree. Surface the disagreement rather
  than picking a winner.
* Criteria changes are code changes with tests, not prompt edits.

## Evidence
`verify_llm.py` runs both vLLM and Ollama, reports what each extracted, then shows
Python deciding independently from the original text. See ADR-0008 for what
happened when the extraction was wrong.
