# ADR-0010: Every finding quotes its evidence, and the metrics can fail

**Status:** Accepted

## Context
`Finding.grounded` was true when a finding had evidence. The criteria engine never attached any,
so no finding was grounded. Nobody noticed because the evaluation's grounding score was written as
`satisfied is not None or grounded or satisfied is None`, which is true for every finding. The
gate reported a perfect grounding score for a system that grounded nothing.

The citation score had the same problem from the other side. It returned a constant, so a quote
invented by a model could never lower it.

## Decision
* Each rule returns the sentence it relied on. `evaluate()` attaches it as `Evidence`, quoted
  exactly from the application. For a setback of 1.4 m the quote is "Setback from the rear
  boundary is 1.4 m".
* A rule satisfied because a trigger is absent, such as no mention of flood zone 3, records
  `absence_checked=True`. The search over the whole text is its grounding, because there is no
  sentence to quote for something that is not there.
* `decide` allows a grant only when every finding is determined and grounded.
* The grounding score now counts a determined finding with no quote and no absence check as a
  failure.
* The citation score checks every quote taken from the application against the application text.
  One quote that does not appear scores the case 0. A partial score would let a mostly correct
  answer hide one invented quote, and `check_output` already treats a phantom citation as fatal.

## Consequences
* Two new mutations in `test_gate_can_fail.py`: M5 strips all evidence and expects grounding 0; M6
  inserts the quote "Setback 9.9 m" and expects citation 0. Both are caught.
* Writing the quote tests exposed two rule bugs, fixed in the same change. A stated setback of 0 m
  was skipped because `a or b` treats 0 as missing. The heritage pattern `grade [I|II]` was a
  character class that matched "grade |" and missed "Grade II*".
* Findings in the graph state now carry their evidence, so an officer reviewing a referral sees the
  sentences behind each finding.

## Open questions
* Quotes are matched as exact text. An application submitted as a scanned PDF would need its text
  extraction checked before the quotes mean anything.
