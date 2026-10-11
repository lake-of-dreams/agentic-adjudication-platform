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
Split on a period unless it has a digit on both sides, which is the only place a decimal point
sits:

    _SENT = re.compile(r"(?<!\d)[.;\n]|[.;\n](?!\d)")

**Revised.** The first version, `(?<!\d)[.;\n](?!\d)`, refused to split when a digit
stood on *either* side. "Site is in flood zone 3. A flood risk assessment is attached." stayed one
sentence, so the flood rule quoted the wrong sentence and a sentence ending in a number swallowed
the next. Regression test: `test_sentence_ending_in_a_number_is_split`.

## Consequences
* Abbreviations split badly. **Revised again:** "Height approx. 3.2 m." split after "approx",
  the height rule found no number beside "Height", and the applicant would have been asked for a
  figure they had given. The splitter now joins after "approx.", "ca." and "No." when a digit
  follows, and after "Mr", "Mrs" and "Ms" when a capital follows. "St.", "Rd." and "Dr." still
  split, because joining two real sentences is the dangerous error: "The setback is measured from
  Mill St. Height 3.2 m." as one sentence gives C1 a setback of 3.2 m and a pass. Splitting too
  often only loses a figure, which sends the case to an officer. Regression tests:
  `test_abbreviation_before_a_number_does_not_lose_the_number` and
  `test_a_street_abbreviation_still_ends_a_sentence`.
* Regression test: `test_decimal_measurements_are_not_split`.
* Test any regex over regulated text against the numeric formats that actually turn
  up in it. A tokeniser bug in a rules engine presents as missing data, not as a bug.
