# ADR-0002: Supervisor topology, not a swarm

**Status:** Accepted

## Context
A swarm is the attractive option. Agents hand off to each other directly, no
coordinator to maintain, easy to add another agent later.

The problem is where the routing decision lives. In a swarm it is made inside
each agent, so no single component knows why a case went where it went. To
reconstruct an outcome you interrogate every agent that touched it, in order, and
hope each one logged enough. Quality also degrades along long handoff chains and
the degradation is invisible, because nothing sees the whole path.

Here the routing decision is itself evidence. "Why was this referred rather than
granted" is the question an appeal turns on, and answering it by reassembling
state from three agents is not an answer.

## Decision
Supervisor topology. One node decides routing and writes one audit record with
the decision, the reason, and the statutory deadline in force.

## Evidence
`compare.py` runs both topologies over the same cases and counts the components
holding routing state:

| case | supervisor | swarm |
|---|---|---|
| clean | 1 | 3 |
| unmet | 1 | 2 |
| unknown | 1 | 3 |
| injection | 1 | 1 |

Same decisions both ways. Different cost to explain them: one record versus up to
three scattered component states.

## Consequences
* The supervisor is a bottleneck and a single point of failure. Acceptable, since
  it does no model work, only routing.
* `adjudication/agents/swarm.py` stays in the tree so the comparison remains
  runnable and the decision stays falsifiable.
