# ADR-0001: The system may grant. It may never refuse.

**Status:** Accepted

## Context
The two mistakes an adjudicator can make do not cost the same.

A wrongly granted permit is recoverable. It can be revoked, inspected,
remediated, fined. A wrongly refused permit is not: by the time an appeal is
heard the applicant has already lost the build season, the financing or the
contract, and none of that comes back.

Symmetric automation ignores that. If the system is equally willing to grant and
to refuse, it ends up optimising one accuracy number across two outcomes with
very different costs, and the number looks fine either way.

## Decision
Automation is asymmetric. The system may issue GRANT on its own evidence. It may
never issue REFUSE. An unmet criterion produces REFER_TO_OFFICER.

Three independent enforcement points, not one prompt instruction:

1. `adjudication/agents/graph.py::supervisor` — unmet criteria route to
   REFER_TO_OFFICER.
2. `adjudication/runtime/guardrails.py::check_action` — a REFUSE decision is
   rejected at the action layer even if the supervisor emitted one.
3. `tests/test_invariants.py::test_system_never_issues_a_refusal` — parametrised
   over every narrative x tier combination.

They are independent on purpose. Removing the constraint by accident takes three
edits rather than one, and the test fails before the other two are noticed.

## Consequences
* More escalations than a symmetric design would produce. Intended, and budgeted
  for by the automation clock (ADR-0003).
* The officer queue is the capacity constraint, not the model.
