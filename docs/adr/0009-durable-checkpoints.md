# ADR-0009: Keep checkpoints in SQLite so a waiting case survives a restart

**Status:** Accepted

## Context
A referred case pauses at `interrupt()` and waits for an officer. The wait can last days. LangGraph
saves the paused state as a checkpoint, and the graph resumes from it when the officer answers.

The graph compiled with `InMemorySaver`, which keeps checkpoints in the process's memory. A
restart, a deploy or a crash while a case waited lost the case. The resume test passed only
because it resumed in the same process that paused.

## Decision
`durable_checkpointer(path)` in `adjudication/agents/graph.py` returns a `SqliteSaver` from
langgraph-checkpoint-sqlite over a SQLite file. SQLite is a database held in one file with no
server. `build_graph` takes a `checkpointer` argument and uses the in-memory saver only when none
is given, which keeps the demo and the tests that need no persistence fast.

## Consequences
* `test_case_resumes_in_a_new_graph_from_sqlite` pauses a case in one graph, deletes that graph,
  builds a second graph over the same file and resumes the case there.
* A checkpoint is not durable execution. A crash in the middle of an outside call repeats the call
  on resume.
* **Corrected.** This record said every side effect before the pause was internal. It was not:
  `escalate` appended "suspended_for_officer" to the audit log and then called `interrupt`.
  LangGraph re-runs an interrupted node from its first line on resume, so every referred case
  logged its suspension twice, with no crash involved. The append moved to its own node, `refer`,
  which finishes before the pause and is never re-run. `escalate` now has nothing with an outside
  effect before `interrupt`. Tests: `test_resume_does_not_write_the_suspension_twice`, and the
  SQLite resume test now asserts the resumed process writes no second suspension.
* The SQLite connection is opened with `check_same_thread=False` because LangGraph may use it from
  more than one thread.

## Open questions
* One SQLite file serves one host. Several workers sharing cases need a shared store, such as the
  PostgreSQL saver.
* Checkpoints hold the redacted narrative and findings. Retention and deletion rules for them need
  sign-off from whoever owns the authority's records policy.
