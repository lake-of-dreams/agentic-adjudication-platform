# Guide 7. Pausing for an officer, from zero

## How to read this guide

**Who it is for.** Engineers building AI workflows that must stop and wait for a person, sometimes
for days. You should be able to read Python. You do not need to know LangGraph, checkpoints or
durable execution. Each is explained when it first appears.

**What you will know at the end.** How a case in this system stops at an officer's desk, survives
the program being restarted while it waits, and carries on when the officer answers. You will know
the one rule that makes a paused step safe to resume, and the bug that taught it: a step that
quietly ran twice.

**How it is organised.**

1. Part 1 explains why the system has to wait for a person at all.
2. Part 2 explains the graph, the state and a node.
3. Part 3 explains how a case pauses and resumes.
4. Part 4 explains the re-run: what really happens on resume, and the bug it caused.
5. Part 5 gives the rule for writing a node that pauses, with the fix.
6. Part 6 explains why checkpoints moved into a database file.
7. Part 7 explains the difference between a checkpoint and durable execution.
8. Part 8 lists the tests.
9. Part 9 lists the design principles.
10. Part 10 lists what is unresolved.

A glossary at the end defines every term.

You can read it front to back like a short book. Each part builds on the one before it.

## The idea in one paragraph

When the system cannot decide a planning application on its own, it hands the case to an officer
and stops. The officer may answer in an hour or in a week. In that time the program may be updated
or restarted, so the case is saved to a file, and picked up from the file when the answer comes.
When it is picked up, the step that stopped is run again from its start. Anything that step did
before it stopped happens a second time. The first version wrote "case suspended" to the audit log
before stopping, so every referred case recorded its suspension twice. The fix moves that write into
its own step, which finishes before the pause and is never run again.

## A note on accuracy

The code is in `adjudication/agents/graph.py`. The tests are in `tests/test_invariants.py` and
`tests/test_grounding_and_scope.py`. The decision record is ADR-0009, which was corrected when the
bug in Part 4 was found. The library is LangGraph 1.2.14 with langgraph-checkpoint-sqlite 3.1.1.
Every log count in this guide is real output from the code.

Simplified for teaching: the officer's answer is passed in by a test or the demo script, not by a
real case-management screen.

## The running example

Ms Priya Nair applied to build a garden studio at 14 Orchard Row, Millbrook. The README's running
example has a second version of her application, Application B, identical except that it states a
setback of 0.6 m. The rule requires at least 1.0 m, so criterion C1 is not met. The system may
recommend a grant, but it may never refuse on its own (README Part 1.2). So it refers the case to an
officer.

Officer off-12 picks it up later. Ms Nair has offered to move the studio back to 1.2 m, and off-12
answers "GRANT, the applicant moved the studio back".

The names are invented. The log entries and their counts are real output.

---

## Part 1. Why the system waits

Some decisions belong to a person by law. This system does the checking and prepares the case, but
an unmet rule is never turned into a refusal by a machine. It goes to an officer.

### 1.1 The cost of waiting badly

If the system cannot wait properly, two things go wrong. Either the case is lost when the program
restarts, and the applicant hears nothing. Or the system starts the case again from scratch, and
everything it recorded is recorded a second time. The second failure is quieter and, as Part 4
shows, it happened.

### 1.2 What waiting properly needs

| Need | Plain meaning | In the running example |
|---|---|---|
| Stop cleanly | The case halts at a known point and nothing runs until the answer arrives | Application B stops at the officer's desk |
| Survive restarts | The paused case is kept somewhere that outlives the program | The case is saved to a file |
| Resume exactly | When the answer arrives, the case carries on from where it stopped | Off-12's GRANT is applied to Application B |
| Record once | Every event appears in the audit log exactly once | One "suspended" entry, one "decided" entry |

## Part 2. The graph, the state and a node

The system is built with LangGraph, a library for programs made of steps that share one record.

### 2.1 The state

The **state** is the shared record of one case: the application text, the findings, the routing
decision and a trace of which steps ran. Every step reads it and returns changes to it. LangGraph
merges those changes in.

### 2.2 Nodes and edges

Each step is a **node**: an ordinary Python function that takes the state and returns an update.
The connections between nodes are **edges**. Together they form a **graph**.

```
intake ─► guard_input ─► retrieve ─► guard_context ─► assess ─► supervisor ─► decide ─┬─► END
                                                                                      │
                                                                                      └─► refer ─► escalate ─► END
```

*Figure 1. The graph. Look at the lower branch: `refer` records the referral, then `escalate`
waits for the officer. Part 5 explains why they are two nodes and not one.*

### 2.3 The audit log sits outside the state

The audit log is not part of the state. It is a separate, hash-chained record (README Part 2.3),
because it must outlive any one run and must not be rewritten by the graph. Nodes append to it as a
**side effect**: something a function does to the world beyond returning a value.

Keep that phrase in mind. Every problem in this guide is about side effects.

## Part 3. Pausing and resuming

### 3.1 The interrupt

To pause, a node calls LangGraph's `interrupt` function with a payload: what the officer needs to
see. The graph stops at that line. The caller of the graph receives the payload and a marker saying
the graph is waiting.

### 3.2 The checkpoint

When the graph stops, LangGraph saves the state under the case's thread id. That saved copy is a
**checkpoint**. It records the state and which node was running.

### 3.3 Resuming

To resume, the caller invokes the graph again with the same thread id and a `Command(resume=...)`
holding the officer's answer. LangGraph loads the checkpoint and carries on.

### 3.4 Application B, step by step

1. The graph runs `intake` to `decide` for Application B. Seven entries are written to its audit log.
2. `decide` sends the case down the referral branch, because the supervisor routed it to
   REFER_TO_OFFICER.
3. `refer` writes "suspended_for_officer" to the audit log. The log now has 8 entries.
4. `escalate` calls `interrupt` with the case id, the reason and the findings.
5. LangGraph saves a checkpoint and returns control to the caller.
6. Days pass. The program may stop and start any number of times.
7. Officer off-12 answers GRANT.
8. The caller invokes the graph with the case's thread id and `Command(resume=...)`.
9. LangGraph loads the checkpoint and runs `escalate` again from its first line.
10. This time `interrupt` returns off-12's answer instead of stopping.
11. `escalate` writes "decided" to the audit log. The log now has 9 entries.
12. The graph ends with the decision GRANT and the officer recorded as the decision maker.

Step 9 is the one this guide is about.

## Part 4. The re-run, and the bug it caused

### 4.1 What really happens on resume

It is natural to picture resuming as continuing from the line where `interrupt` was called, like a
paused video. That is not what happens. LangGraph cannot save the inside of a running Python
function. It saves the state between nodes. So on resume, it runs the interrupted node again from
its first line. The second time, `interrupt` does not stop: it returns the resume value.

Everything in the node before `interrupt` therefore runs twice: once before the pause, and once on
resume.

### 4.2 The first version

The first version had one node for the whole referral:

```python
def escalate(state):
    audit.append(case_id, "system:escalate", "suspended_for_officer", ...)
    officer = interrupt({...})
    audit.append(case_id, f"officer:{officer_id}", "decided", ...)
    return {...}
```

Read it with Part 4.1 in mind. The first `audit.append` is before `interrupt`. It runs when the case
pauses, and runs again when the case resumes.

**Example.** Application B paused with 8 log entries. On resume, `escalate` ran from its first
line: it appended "suspended_for_officer" a second time, then `interrupt` returned off-12's answer,
then it appended "decided". The log ended with 10 entries, not 9.

```
[24] system:escalate   suspended_for_officer
[25] system:escalate   suspended_for_officer
[26] officer:off-014   decided
```

*Figure 2. The end of the demo's audit log before the fix. Entries 24 and 25 are the same event,
recorded twice.*

### 4.3 Why it went unnoticed

No error was raised. Every test passed. The existing resume test checked that an officer entry
appeared, and it did. Nobody counted the suspension entries.

It surfaced when the demo script's output was read line by line, and two identical entries sat next
to each other. An audit log exists so that someone can later say exactly what happened to a case. A
log that records one suspension as two says something false about the case, and nothing marks which
entry is the real one.

### 4.4 It would have been worse elsewhere

Here the repeated side effect was a log line. Had the node sent an email to the applicant before
pausing, the applicant would have received it twice. Had it called a payment system, the payment
would have run twice. The bug's shape is the same. Only the damage changes.

## Part 5. The rule for a node that pauses

**Inside a node that pauses, nothing with an effect outside the graph's state may come before
`interrupt`.**

### 5.1 The fix

The write moved into its own node:

```python
def refer(state):
    audit.append(case_id, "system:escalate", "suspended_for_officer", ...)
    return {"trace": ["refer"]}

def escalate(state):
    # nothing with a side effect before interrupt(): it all runs twice
    officer = interrupt({...})
    audit.append(case_id, f"officer:{officer_id}", "decided", ...)
    return {...}
```

The graph now runs `decide`, then `refer`, then `escalate`. `refer` finishes before the pause.
LangGraph records that it finished, so on resume it starts from `escalate` and never runs `refer`
again. The log for Application B ends with 9 entries.

### 5.2 Why not make the write idempotent instead

Another fix would keep one node and make the write **idempotent**: safe to repeat, because a second
identical write changes nothing. The audit log could skip an entry it has already recorded.

That would work, but it spreads the knowledge of the re-run into the audit log, which should not
need to know how its callers are scheduled. It also makes every future side effect in every pausing
node need the same care. Moving the write into a finished node makes the problem impossible by
construction. Idempotency remains the right tool when an outside call cannot be moved, which Part 7
returns to.

### 5.3 What can safely come before interrupt

Work with no outside effect is safe to repeat: reading the state, building the payload for the
officer, computing values. Running it twice gives the same result and touches nothing.

## Part 6. Why checkpoints moved into a database file

### 6.1 Memory is lost on restart

LangGraph's simplest checkpointer, `InMemorySaver`, keeps checkpoints in the program's memory. If
the program stops while Application B waits for off-12, the checkpoint is gone. When off-12 answers,
there is no case to resume.

### 6.2 SQLite

The checkpoints can now be kept in **SQLite**, a database that lives in one file and needs no
server. `durable_checkpointer(path)` in `graph.py` opens the file and returns a saver for it. A new
program, started later, opens the same file and finds the case.

**Example.** The test `test_case_resumes_in_a_new_graph_from_sqlite` pauses a case in one graph,
throws that graph away, builds a second graph on the same file, and resumes the case there with an
officer's GRANT. The case completes in the second graph.

### 6.3 The restart test also counts

That test now also checks that the second program writes no second "suspended_for_officer" entry.
Before the fix, the resumed process re-ran the whole `escalate` node, so it wrote one. After the
fix, it starts at `escalate`, after `refer` has finished, and writes only the officer's decision.

### 6.4 One file serves one machine

A SQLite file is local to one machine. Several copies of the program sharing cases need a shared
store, such as a PostgreSQL database with LangGraph's PostgreSQL saver. The same is true of the
store of spent confirmation tokens in Guide 5, Part 6.

## Part 7. A checkpoint is not durable execution

A **checkpoint** saves the state between nodes. **Durable execution** goes further: it guarantees
that each outside effect happens exactly once, even if the program crashes in the middle of a node.

### 7.1 The gap

Suppose a node calls an outside service, and the program crashes after the service has acted but
before the node finishes. On restart, the checkpoint says the node did not finish, so the node runs
again, and the outside service acts a second time. A checkpoint cannot prevent this, because it
never saw the call complete.

### 7.2 What this repository does about it

There are three tools, used in this order of preference.

1. **Keep the outside effect out of the node that might repeat.** Part 5's fix is this.
2. **Make the outside effect idempotent.** Give each call a unique key, and have the receiver ignore
   a key it has seen. The confirmation store in Guide 5 does this for permits: the token id can be
   spent once.
3. **Use a durable execution engine** that records each outside call's result and replays the
   result instead of repeating the call. This repository does not use one.

### 7.3 A correction on the record

ADR-0009 originally said that every side effect before the pause was internal, so the gap did not
matter here. It was wrong: the audit log is outside the graph's state, and its write ran twice
without any crash at all. The record now says so, and names the tests that hold the fix.

## Part 8. The tests

| Test | What it proves | File |
|---|---|---|
| `test_interrupt_suspends_and_resume_continues_same_case` | A referred case pauses, and resuming applies the officer's decision | `test_invariants.py` |
| `test_resume_does_not_write_the_suspension_twice` | After resume, the log holds exactly one suspension and one decision | `test_invariants.py` |
| `test_case_resumes_in_a_new_graph_from_sqlite` | A case paused in one program resumes in another, and the second writes no second suspension | `test_grounding_and_scope.py` |

Both new assertions were checked by running them against the old graph. Both failed there: the
first counted 2 suspensions, the second counted 1 in the resumed process. Both pass on the fixed
graph.

## Part 9. Design principles

**1. A paused node runs twice.** Write every pausing node as if its code before `interrupt` will run
on pause and again on resume, because it will.

**2. Side effects go in nodes that finish before the pause.** A finished node is never re-run.

**3. Count what you log.** A test that checks an entry appears will pass on a duplicate. Check how
many.

**4. A checkpoint is not durable execution.** It saves state between nodes, not calls inside them.
Outside calls need their own guard against repeating.

**5. Correct the record when it was wrong.** The decision record that said this could not happen
now says that it did.

## Part 10. What is unresolved

1. **One machine's checkpoints.** SQLite serves one host. Several workers need a shared store such
   as PostgreSQL (Part 6.4).
2. **Retention.** Checkpoints hold the redacted application and findings. How long they are kept,
   and how they are deleted, needs a records-management decision.
3. **No durable execution engine.** A crash inside a node that calls an outside system repeats the
   call. Every such call today is either idempotent or absent, but nothing enforces that for the
   next node someone writes.
4. **The audit log is in memory in the demo.** It is meant to sit on write-once storage. Which
   storage, and who may read it, is not decided.

## Glossary

| Term | Plain meaning | Explained in |
|---|---|---|
| Audit log | The hash-chained record of every step taken on a case, kept outside the state | Part 2.3 |
| Checkpoint | The state saved between nodes, so a paused case can resume | Part 3.2 |
| `Command(resume=...)` | How the caller hands the officer's answer back to a paused graph | Part 3.3 |
| Durable execution | Guaranteeing each outside effect happens exactly once, even after a crash | Part 7 |
| Edge | A connection from one node to the next | Part 2.2 |
| Graph | The nodes and edges that make up the program | Part 2.2 |
| Idempotent | Safe to repeat: doing it twice has the same effect as doing it once | Part 5.2 |
| `InMemorySaver` | LangGraph's checkpointer that keeps checkpoints in memory; lost on restart | Part 6.1 |
| Interrupt | LangGraph's way of pausing a graph until outside input arrives | Part 3.1 |
| LangGraph | A library for programs made of steps that share one record | Part 2 |
| Node | One step of the graph: a function that reads the state and returns an update | Part 2.2 |
| PostgreSQL | A database server that several programs can share | Part 6.4 |
| Re-run on resume | LangGraph running an interrupted node again from its first line | Part 4.1 |
| Side effect | Something a function does to the world beyond returning a value | Part 2.3 |
| SQLite | A database that lives in one file and needs no server | Part 6.2 |
| State | The shared record of one case that every node reads and updates | Part 2.1 |
| Thread id | The key a case's checkpoints are saved under | Part 3.2 |
