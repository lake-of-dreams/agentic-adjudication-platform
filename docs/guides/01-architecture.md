# Guide 1 — Architecture

Adjudicates permit applications against published criteria. It may recommend a
grant, never a refusal, and it can reconstruct any decision it made from a
tamper-evident log.

## Why this shape

Three properties of the domain drive most of the design:

1. Wrongly granting is recoverable, wrongly refusing is not, so the automation is
   asymmetric too (ADR-0001).
2. The deadline is fixed in law, not an SLO. The clock is domain logic (ADR-0003).
3. An appeal turns on why, not what. The decision path is the evidence.

## Flow

    intake ──► guard_input ──► retrieve ──► guard_context ──► assess
                                                                │
                                                          supervisor
                                                          ╱         ╲
                                                    decide          escalate
                                                       │               │
                                                      END        interrupt()
                                                                       │
                                                              (officer resumes)
                                                                       │
                                                                      END

| Node | Does | Does not |
|---|---|---|
| `intake` | redact PII, start audit | interpret anything |
| `guard_input` | screen applicant text (4 attack classes) | call a model |
| `retrieve` | BM25 + dense → RRF → rerank | decide relevance by model |
| `guard_context` | screen retrieved docs for indirect injection | trust retrieval |
| `assess` | apply deterministic criteria | use the model for arithmetic |
| `supervisor` | decide routing, record why | do model work |
| `decide` | independent action-layer check | trust the supervisor |
| `escalate` | suspend via `interrupt()` | invent a human decision |

## Trust boundaries

* **Applicant text** — untrusted. Screened at `guard_input`, redacted at intake.
* **Retrieved documents** — untrusted even though internally stored, because the
  applicant may have uploaded them. Screened at `guard_context`.
* **Model output** — untrusted for decisions. Reading only (ADR-0006).
* **Officer decision** — trusted, recorded with the officer's id.

## Where each capability lives

| Capability | File |
|---|---|
| LangGraph StateGraph, checkpointing, interrupt/resume, RetryPolicy | `adjudication/agents/graph.py` |
| Four-layer guardrails | `adjudication/runtime/guardrails.py` |
| Tool registry: entitlement, effect ceiling, argument scope | `adjudication/runtime/tools_registry.py` |
| Hash-chained audit, tamper detection, reconstruction | `adjudication/runtime/audit.py` |
| Reversible typed PII redaction | `adjudication/runtime/redaction.py` |
| BM25 from formula, RRF, cross-encoder rerank | `adjudication/retrieval/hybrid.py` |
| Trajectory metrics, 8 runs, gate on worst | `adjudication/eval/` |
| MCP server with delegated authorisation | `adjudication/mcp_server/server.py` |
| Signed A2A agent card | `adjudication/a2a/agent_card.py` |
| OWASP red-team suite | `adjudication/redteam/suite.py` |
| Supervisor vs swarm measurement | `compare.py` |
