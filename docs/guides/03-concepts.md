# Guide 3 — Concepts

Reference for the mechanisms this repo leans on, written out properly because I
will not remember the details in six months.

## BM25

    score(D,Q) = Σᵢ IDF(qᵢ) · ( f(qᵢ,D)·(k₁+1) ) / ( f(qᵢ,D) + k₁·(1 − b + b·|D|/avgdl) )

* **IDF** — rare terms matter more. Robertson–Sparck-Jones with +0.5 smoothing,
  clamped non-negative so terms appearing in most documents do not score negatively.
* **k₁ (1.5)** — term-frequency saturation. As f grows the score approaches
  `IDF·(k₁+1)`. Low k₁ saturates fast: the 5th occurrence adds almost nothing over
  the 4th. Without it, keyword-stuffed documents win.
* **b (0.75)** — length normalisation. b=1 fully penalises long documents, b=0
  ignores length. 0.75 is the usual compromise.

In a small corpus a term appearing in no document gets maximum IDF. Correct
behaviour, looks odd in a five-document demo.

## RRF — reciprocal rank fusion

    RRF(d) = Σ_r 1 / (k + rank_r(d))     k = 60

Consumes ranks only and throws the scores away. BM25 scores and cosine
similarities are on incomparable scales, so fusing the numbers means inventing a
weighting, and that weighting drifts as the corpus changes without anyone
noticing. k=60 flattens the curve near the top so a single confident-but-wrong
retriever cannot dominate.

## Bi-encoder vs cross-encoder

* **Bi-encoder** — embeds query and document separately, compares vectors.
  Precomputable, fast, less accurate. First-stage dense retrieval.
* **Cross-encoder** — feeds `(query, document)` through the model jointly and
  scores the pair. More accurate, cannot be precomputed, so only viable over a
  shortlist.

Retrieve broad and cheap, rerank narrow and expensive.

## Direct vs indirect prompt injection

* **Direct** — the user tells the model to ignore its instructions. Easy to
  detect, rare in practice.
* **Indirect** — instructions sit inside content the system retrieves and trusts.
  The attacker never talks to the model.

Indirect is the more realistic attack because the payload arrives through a
trusted channel. Over-focusing on it is what left a direct hole in this repo,
see ADR-0004.

## The confused deputy

A privileged component performs an action on behalf of a less privileged one
without checking the caller's authority. Agents are natural confused deputies:
they hold broad access by construction. Three defences apply here: entitlement, an
effect ceiling of `min(agent, human)`, and argument scope.

## Hash chaining

Entry *n* stores `hash(content_n ‖ hash_{n-1})`. Changing anything invalidates
every subsequent hash.

Not a blockchain. No distributed consensus, no proof of work. It gives tamper
*evidence*, not tamper *prevention*: anyone with write access can rewrite the whole
chain. That is why the chain is append-only at the application layer and the store
is write-once at the infrastructure layer.

## LangGraph: checkpointing vs durable execution

* **Checkpointing** — persists graph state so a run can resume. `InMemorySaver`
  keeps it in the process and loses it on restart. `durable_checkpointer(path)`
  keeps it in a SQLite file, so a case paused in one process resumes in another
  (ADR-0009). Several hosts sharing cases would need a Postgres saver.
* **Durable execution** — exactly-once side effects, durable timers, compensation
  on failure. Temporal, Camunda.

Checkpointing is not durable execution. If the graph calls an external API and
crashes mid-call, checkpointing will replay it. Here the window is days and the
side effects are internal, so checkpointing is sufficient.

## Trajectory metrics

Answer-quality metrics score the destination. Trajectory metrics score the path:
did every guardrail layer run, did tool calls stay inside policy, did cases that
should have escalated actually escalate, does the audit chain verify. The same
answer via a compliant path and a dangerous path scores identically on quality and
differently here.

## Gating on the worst run

With a stochastic component a case has a distribution of outcomes, not one
outcome, and the mean flatters it. One run in eight failing the safety invariant
gives a mean of 0.875 and the system ships. Gating on the worst run means one
violation blocks release, which is the only workable policy for an invariant.

## PII redaction: why right-to-left

Replacing left-to-right invalidates every span offset after the first
substitution, because the placeholder length differs from the original. Applying
in reverse document order keeps the earlier offsets valid. The bug presents as
"the model is ignoring the mask". It is not; the mask went onto the wrong bytes.

Typed placeholders (`[PERSON_1]`) keep the fact that a person was mentioned, so
the model can still reason about roles. `[REDACTED]` destroys that and measurably
degrades answers.

## MCP and A2A

* **MCP** — agent to tool. The 2026-07-28 specification made the core stateless
  and removed sessions, so authorisation context travels with each call instead
  of being established once at initialise. That is what makes per-call delegated
  authorisation natural. The same version lets a server answer "input required"
  and have the client retry with the answers attached. This repository uses that
  to make an irreversible tool wait for a confirmation from the person the agent
  acts for (ADR-0011).
* **A2A** — agent to agent. Version 1.0 lists an agent's addresses under
  `supportedInterfaces` and signs the Agent Card as a JWS over its JCS (RFC 8785)
  canonical form, so a receiving agent can check the card came from whoever holds
  the signing key. Canonicalisation carries the weight: two encodings of the same
  object have to produce identical bytes or the signature fails for reasons that
  look random.

## ES256 and HMAC

Both produce a signature over some bytes. They differ in who can make one.

* **HMAC** — one shared secret signs and checks. Every party able to check a
  signature could also create one.
* **ES256** — an elliptic-curve key pair. The private key signs; the public key
  only checks. A card signed this way can be checked by anyone and forged by
  nobody without the private key (ADR-0012).

JWS wants the ES256 signature as 64 raw bytes, the two numbers r and s side by
side. The `cryptography` library returns a DER-encoded structure instead, so the
code converts between the two.

## Grounding an absence

A finding is grounded when it rests on evidence a reviewer can check. For a
measured criterion that is the sentence it quoted. For a criterion met because
something is absent, such as no mention of flood zone 3, there is no sentence to
quote. The evidence is the search over the whole text, recorded as
`absence_checked` (ADR-0010).
