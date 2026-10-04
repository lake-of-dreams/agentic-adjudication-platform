# ADR-0003: Reserve human headroom inside the statutory clock

**Status:** Accepted

## Context
Determination deadlines are fixed in law. They are not an SLO you can
renegotiate when the queue backs up. Handing a case to an officer with two hours
left on a 28-day statutory clock is not an escalation path, it is a way of moving
the blame.

## Decision
The automated path may consume at most `AUTOMATION_BUDGET = 0.40` of the
statutory window, then hands over regardless of confidence. The remaining 60% is
the officer's.

`adjudication/domain/clock.py` exposes `must_hand_over(now)` and the supervisor
consults it as a routing condition alongside the criteria outcome.

## Consequences
* Some cases the system could have decided are escalated on time alone. That is
  the trade.
* Tested per tier: `test_every_tier_reserves_headroom`.
