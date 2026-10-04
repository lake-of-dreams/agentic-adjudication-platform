# ADR-0005: Never split sentences on a bare period

**Status:** Accepted
**From a real bug, found by the first smoke test.**

## Context
The criteria engine finds a measurement by locating the sentence containing a
keyword and pulling the number out of it. Sentences were split on `[.;\n]`.

First real application through it:

    "Setback from boundary is 1.4 m. Overall height 3.2 m."

split into `"Setback from boundary is 1"`, `"4 m"`, `"Overall height 3"`, `"2 m"`.
The keyword sentence no longer had a measurement in it, so both rules came back
"no setback stated" and "no height stated" for an application that stated both.

I spent a while on the wrong end of this, looking at the keyword matching and the
number regex, because the output looked like the document was missing data rather
than like a parsing failure. Nothing errored. It produced `satisfied=None`, which
routes to REQUEST_INFORMATION, so the system asked the applicant for information
they had already given it.

## Decision
Split on a period only when it is not between digits:

    _SENT = re.compile(r"(?<!\d)[.;\n](?!\d)")

## Consequences
* Abbreviations ("No. 14 High St.") still split badly. Fine for now, no measurement
  depends on them.
* Regression test: `test_decimal_measurements_are_not_split`.
* Test any regex over regulated text against the numeric formats that actually turn
  up in it. A tokeniser bug in a rules engine presents as missing data, not as a bug.
