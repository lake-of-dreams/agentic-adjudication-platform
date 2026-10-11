# Guide 6. Reading numbers out of text, from zero

## How to read this guide

**Who it is for.** Engineers who will write or review rules that pull facts out of free text: a
setback from a planning application, a dose from a prescription, an amount from an invoice. You
should be able to read Python and a simple regular expression. You do not need to know anything
about planning law. Each term is explained when it first appears.

**What you will know at the end.** How this repository turns an applicant's sentences into
decisions without a language model, why that is harder than it looks, and why every bug of this
kind looks like missing data rather than an error. You will understand the rule this guide is built
around: when splitting text, the two possible mistakes do not cost the same, so the code is
deliberately lopsided.

**How it is organised.**

1. Part 1 explains why the rules are plain Python and not a model.
2. Part 2 shows how a rule finds a number: the sentence, the keyword and the measurement.
3. Part 3 explains sentence splitting and the decimal bug.
4. Part 4 explains the abbreviation bug and the asymmetric fix.
5. Part 5 explains the same hazard inside one sentence: two figures, and a rule that picks one.
6. Part 6 covers the two smaller rule bugs: zero treated as missing, and a pattern that matched the
   wrong thing.
7. Part 7 explains how each finding quotes its evidence, and how that exposes these bugs.
8. Part 8 lists the tests that hold each fix.
9. Part 9 lists the design principles.
10. Part 10 lists what is unresolved.

A glossary at the end defines every term.

You can read it front to back like a short book. Each part builds on the one before it.

## The idea in one paragraph

The system checks a planning application against five rules, such as "the building must stand at
least 1.0 m from the boundary". To do that it has to find the number in the applicant's text. It
does this by cutting the text into sentences, finding the sentence that talks about the boundary,
and reading the measurement in it. Every step of that can go wrong silently. Cut a sentence in the
wrong place and the number is lost, so the system asks the applicant for something they already
gave. Join two sentences that should be apart and a number can land next to the wrong word, so the
system grants something it should not. The second mistake is far worse than the first, so the code
splits whenever it is unsure, and a rule that finds two numbers in its sentence refuses to pick one.

## A note on accuracy

The rules are in `adjudication/domain/criteria.py`. The tests are in `tests/test_invariants.py`
and `tests/test_grounding_and_scope.py`. The decision record is ADR-0005. Every example result in
this guide is real output from the code.

The five criteria are invented for teaching and belong to no real authority. Real planning rules
are longer and depend on judgement in ways five thresholds cannot capture.

## The running example

Ms Priya Nair applied to build a garden studio at 14 Orchard Row, Millbrook. Her application says:

> Setback from the rear boundary is 1.4 m. Height 3.2 m. Coverage 38% of the plot.

A **setback** is how far a building stands from the edge of its plot. Rule C1 requires at least
1.0 m. Rule C2 allows a height of at most 4.0 m. Rule C3 allows the buildings to cover at most 50%
of the plot. Her studio meets all three.

Through this guide, small changes to her text show each bug. The person and address are invented.

---

## Part 1. Why the rules are plain Python

The rules decide, and a model only ever reads. This split is the subject of ADR-0006 and README
Part 3. This part explains why it matters for numbers in particular.

### 1.1 What an auditor has to do

A planning decision can be appealed. At appeal, someone checks how the decision was reached. For a
measurement rule, that means: find the figure the applicant gave, compare it with the threshold, and
confirm the outcome. That person must be able to repeat the arithmetic and get the same answer.

A language model reading "1.4 m" might extract 1.4 one day and 14 the next, or drop the field
entirely. ADR-0008 measured this: a small model extracted the setback correctly in 0 of 5 runs,
while a larger one got 5 of 5. Neither result can be repeated by an auditor with a pencil.

So the rules are ordinary Python: regular expressions and comparisons. Given the same text, they
give the same answer every time, and anyone can follow them.

### 1.2 The price of plain rules

Plain rules are brittle in a specific way. They do exactly what the pattern says, which is not
always what the writer meant. The bugs in this guide are all of that kind. None of them raised an
error. Each produced a plausible wrong answer.

## Part 2. How a rule finds a number

A measurement rule works in three steps. Each step is a place where a bug can hide.

### 2.1 The three steps

1. **Split** the application into sentences.
2. **Find** the first sentence that contains the rule's keyword, such as "setback" or "height".
3. **Read** the first measurement in that sentence: a number followed by "m", "metre" or "meter".

If no sentence contains the keyword, or that sentence has no measurement, the rule reports that the
figure was not stated. Its result is then `None`, which means undetermined. An undetermined
criterion is never treated as met. The case asks the applicant for the figure, or goes to an
officer.

### 2.2 Why the measurement must come from the same sentence

Imagine a simpler rule: find the word "setback", then take the first number anywhere in the text.

**Example.** An application reads: "Plot 7, extension 2 storeys. Setback is 0.6 m." The first
number in the whole text is 7. A rule that took it would see a setback of 7 m and pass C1. The true
setback is 0.6 m, which fails.

Reading only inside the keyword's own sentence is what stops a number from one statement being read
as the answer to another. It is also why where the sentences start and end matters so much. The
whole rest of this guide follows from that.

### 2.3 Undetermined is the safe answer

When a rule cannot find its figure, it says so. That outcome is safe: the case asks for information
or goes to a person. It costs time but never produces a wrong decision.

A wrong figure is not safe. It produces a confident result that may be the opposite of the truth.
Keep this asymmetry in mind. In Part 4 it decides how the splitter is built.

## Part 3. Splitting sentences and the decimal bug

The first splitter cut the text at every full stop, semicolon and line break. That works for most
prose and fails on the one thing these rules read: numbers.

### 3.1 The bug

The splitter treated the full stop inside "1.4" as the end of a sentence.

```
"Setback from the rear boundary is 1.4 m."
   becomes
"Setback from the rear boundary is 1"   and   "4 m"
```

The first piece contains the keyword and no measurement, because "1" is not followed by "m". The
second piece contains a measurement and no keyword. So the setback rule reported "no boundary
setback stated", and the system asked Ms Nair for a figure she had already given.

Nothing raised an error. To the system, and to anyone reading its output, it looked as if the
applicant had left something out. This is the lesson ADR-0005 records: **a tokeniser bug in a
rules engine looks like missing data, not like a bug.** A **tokeniser** is any code that cuts text
into pieces.

### 3.2 The first fix went too far

The first fix refused to split at any full stop with a digit next to it, on either side. That kept
"1.4" whole. It also stopped this text splitting:

> The site is in flood zone 3. A flood risk assessment is attached.

The full stop after "3" has a digit before it, so the two sentences stayed joined. The flood rule
then quoted the wrong sentence as its evidence. Worse, any sentence ending in a number swallowed the
sentence after it.

### 3.3 The fix that holds

A decimal point is the only full stop with a digit on **both** sides. The splitter now refuses to
split only there.

```python
_SENT = re.compile(r"(?<!\d)[.;\n]|[.;\n](?!\d)")
```

Read it as: split at a full stop, semicolon or line break that either has no digit before it, or
has no digit after it. Only "1.4", with digits on both sides, survives whole. "zone 3. A" splits,
because no digit follows the full stop.

## Part 4. Abbreviations, and why the fix is lopsided

The decimal fix left one gap. Applicants write abbreviations, and an abbreviation ends in a full
stop.

### 4.1 The bug

> Height approx. 3.2 m.

The full stop after "approx" has a letter before it and a space after it. The splitter cut there:

```
"Height approx"   and   " 3.2 m"
```

The height rule found the keyword "Height" in the first piece, with no measurement. It reported
"no height stated". Ms Nair would have been asked for a height she had given. This is the same
failure as the decimal bug, in a new place.

### 4.2 The obvious fix is dangerous

The obvious fix is a list of abbreviations after which the splitter should not cut: "approx.",
"No.", "St.", "Rd.", "Dr.", "Mr." and so on. Some of those can also end a sentence.

**Example.** An application reads:

> The setback is measured from Mill St. Height 3.2 m.

If "St." never ends a sentence, these become one sentence: "The setback is measured from Mill St.
Height 3.2 m". The setback rule finds the keyword "setback" in it, then the first measurement, which
is 3.2 m. Since 3.2 m is more than the 1.0 m minimum, C1 passes. The applicant never gave a
setback. The figure the rule read is the height.

That is a wrong grant, produced silently, from a fix for a harmless bug.

### 4.3 The two mistakes do not cost the same

Put the two possible errors side by side.

| Mistake | What happens | Cost |
|---|---|---|
| Splitting where you should not | A number is separated from its keyword; the rule reports it missing | An officer or applicant spends time supplying a figure already given |
| Joining where you should not | A number lands next to another rule's keyword | A rule can pass on the wrong figure, and the case may be granted wrongly |

Splitting too often is the safe direction. Joining too often is the dangerous one. So the splitter
joins only where it is certain the full stop does not end a sentence.

### 4.4 The fix

The splitter joins after an abbreviation only when two conditions hold: the word is one that cannot
end a sentence, and what follows is what that abbreviation always precedes.

| Abbreviation | Joined when followed by | Why it cannot end a sentence |
|---|---|---|
| `approx.`, `ca.` | a digit | "approximately" and "circa" always come before a quantity |
| `No.` | a digit | "number" as a label always comes before the number |
| `Mr`, `Mrs`, `Ms` | a capital letter | a title always comes before a name |

"St.", "Rd." and "Dr." are left out on purpose. Each can end a sentence ("We live on Mill St.") as
often as it abbreviates. They keep splitting, so the Mill St. example stays two sentences and the
setback rule correctly reports "no boundary setback stated".

**Example.** With the fix in place, "Site is No. 14 Orchard Row. Height approx. 3.2 m. Setback ca.
1.4 m." becomes three sentences: "Site is No. 14 Orchard Row", "Height approx. 3.2 m" and "Setback
ca. 1.4 m". The height rule quotes "Height approx. 3.2 m" and passes C2. The setback rule reads
1.4 m and passes C1.

### 4.5 How it is built

The splitter still uses the pattern from Part 3.3 to find candidate split points. For each full stop
it finds, it looks at the word just before it and the first character after it. If they match a row
of the table, it skips that split. Everything else splits as before.

The code is in `_is_abbreviation` and `_sentences` in `adjudication/domain/criteria.py`.

## Part 5. Two figures in one sentence

Part 4 kept two sentences from being joined. The same hazard exists inside a single sentence, and
it was found while writing this guide.

### 5.1 The bug

> Height 3.2 m, 0.4 m from the boundary.

This one sentence mentions the boundary, so the setback rule reads it. It then takes the first
measurement in it, which is 3.2 m: the height. Since 3.2 m is more than the 1.0 m minimum, C1
passes. The applicant's real setback is 0.4 m, which fails.

Ranges went wrong the same way.

> Setback between 0.8 and 1.6 m.

The measurement pattern needs a unit straight after the number. Only "1.6 m" has one, so the rule
read the setback as 1.6 m and passed C1. Part of the building may stand 0.8 m from the boundary.

**Example.** All four of these applications came back with every criterion met, so the system
would have recommended a grant.

| Application text | What the rule read | What the applicant said |
|---|---|---|
| Height 3.2 m, 0.4 m from the boundary | setback 3.2 m | setback 0.4 m |
| Setback between 0.8 and 1.6 m | setback 1.6 m | somewhere from 0.8 to 1.6 m |
| Setback 0.8-1.6 m | setback 1.6 m | somewhere from 0.8 to 1.6 m |
| Coverage 38% of the plot, 70% with the patio | coverage 38% | 70% once the patio is built |

These are the dangerous kind of mistake from Part 4.3: a confident result on the wrong figure.
Nothing raised an error.

### 5.2 Why the rule cannot choose

A rule could try to work out which number belongs to its keyword: the one nearest the word, or the
one after "from". Each guess fails on some ordinary phrasing. "0.4 m from the boundary" puts the
number before the keyword; "the boundary is 0.4 m away" puts it after; "from the boundary, 0.4 m"
separates them with a comma. Getting this right in general means parsing sentence structure, and a
parser's mistakes would themselves need measuring before it decided anything.

So the rule does not choose. That follows the same principle as the splitter: when unsure, take the
outcome that costs time, not the one that can grant wrongly.

### 5.3 The fix

A measurement rule reads its figure only from a sentence that holds exactly one number. If the
sentence holds two or more, the criterion is undetermined, and the reason says so:

```
satisfied: None
rationale: more than one figure in the sentence about the setback; an officer must say which applies
quote:     "Height 3.2 m, 0.4 m from the boundary"
```

The quote is still recorded, so whoever picks the case up sees exactly which sentence was unclear.
The coverage rule follows the same rule for percentages.

With the fix, all four applications in the table above ask the applicant for the figure instead of
being granted.

### 5.4 The cost

Some clear sentences now go to a person. "At No. 14 the setback is 1.4 m" holds two numbers, 14
and 1.4, so C1 is undetermined although a human reader sees no doubt at all. That is the price of
the safe direction, recorded in Part 10.

### 5.5 Also an attack

An applicant who knows how the rule reads text could write two figures on purpose to get a grant.
That makes this a security case as well as a bug. The red-team suite (README Part 8.3) now includes
it as RT-11: "two figures in one sentence to feed a rule the wrong one". With the old rule, the
suite reports it as an uncontained finding. With the fix, it is contained.

## Part 6. Two smaller rule bugs

Writing the evidence tests (Part 7) exposed two more bugs, both in how a rule read what it found.

### 6.1 A setback of zero was treated as missing

The setback rule looked for "setback" first, then fell back to "boundary". At the time, the lookup
returned just the number, and the code was:

```python
v = _first_measure(text, "setback") or _first_measure(text, "boundary")
```

Python's `or` returns its right-hand side whenever the left-hand side counts as false. `None`
counts as false, which is what the fallback was for. But `0.0` counts as false too.

**Example.** "Setback 0 m. Distance from the house to the boundary is 2.5 m." The first lookup
found 0.0, the `or` treated it as missing, and the second lookup found 2.5 m in the boundary
sentence. C1 passed on 2.5 m for a building with no setback at all.

The fix uses an explicit `is None` check, so only a genuinely missing value falls through. A stated
setback of 0 m now fails C1 as it should.

### 6.2 A pattern that matched the wrong thing

The heritage rule looks for listed buildings: buildings protected for their history, graded I, II*
or II in England. The pattern was meant to match "grade I" or "grade II":

```
grade [I|II]
```

In a regular expression, square brackets mean "any one of these characters", not "one of these
words". So `[I|II]` meant "one character that is I, or a vertical bar". The pattern therefore
matched "grade |", and "grade I" followed by anything, including "a grade Industrial unit", which
would wrongly treat an ordinary warehouse as listed. It caught "Grade II" only because "Grade II"
starts with "Grade I".

The fix uses alternation, which does mean "one of these words", and handles the star:

```
\bgrade\s+(?:I|II\*?)(?![\w*])
```

## Part 7. Every finding quotes its evidence

Each finding records the exact sentence it relied on, quoted from the application. This is called
**grounding**. README Part 4 explains it in full. This part shows why it matters for the bugs above.

### 7.1 What a quote shows

For Ms Nair's application, the C1 finding records:

```
satisfied: True
rationale: stated setback 1.4 m against minimum 1.0 m
quote:     "Setback from the rear boundary is 1.4 m"
```

Anyone can check that quote against the application. If the splitter had cut at the decimal, the
quote would have been "Setback from the rear boundary is 1", and the mistake would be visible at a
glance.

### 7.2 A quote that is not in the text is refused

The `decide` node checks that every quote really appears in the application. A finding whose quote
was invented, or changed, cannot carry an automated grant. That is why the splitter's output
matters beyond the rules: a sentence boundary in the wrong place produces a quote that is the wrong
sentence, and the evidence trail itself becomes wrong.

### 7.3 Tests that look at the quote

The abbreviation test does not only check that C2 passes. It checks that the quote is exactly
"Height approx. 3.2 m". A rule can pass for the wrong reason. Checking the quote checks the reason.

## Part 8. The tests that hold each fix

| Test | What it proves | File |
|---|---|---|
| `test_decimal_measurements_are_not_split` | "1.4 m" stays whole and C1 and C2 pass | `test_invariants.py` |
| `test_sentence_ending_in_a_number_is_split` | "zone 3. A flood risk assessment" splits | `test_grounding_and_scope.py` |
| `test_abbreviation_before_a_number_does_not_lose_the_number` | "approx.", "ca." and "No." keep their numbers, and the quote is exact | `test_invariants.py` |
| `test_a_street_abbreviation_still_ends_a_sentence` | "Mill St. Height 3.2 m" stays two sentences, so C1 is undetermined, not granted | `test_invariants.py` |
| `test_two_figures_in_one_sentence_are_not_guessed_between` | Five sentences with two figures or a range leave their criterion undetermined | `test_invariants.py` |
| `test_undetermined_is_not_treated_as_satisfied` | No figure means `None`, never `True` | `test_invariants.py` |
| Red-team case RT-11 | An applicant cannot get a grant by writing two figures in one sentence | `adjudication/redteam/suite.py` |

The one-number tests were checked the same way: with the rule switched off, all five cases fail
and RT-11 is reported as a finding. Both abbreviation tests were checked by breaking the code on
purpose. With the abbreviation check
removed, the first test fails. With "st" added to the list of abbreviations to join, the second test
fails: C1 becomes `True` on the height. So each test fails on exactly the mistake it guards against.

## Part 9. Design principles

**1. Rules decide; a model never does.** An auditor must be able to repeat the arithmetic exactly.

**2. Read the number from the keyword's own sentence.** Never the first number in the text.

**3. Unsure means split.** Losing a number sends a case to a person. Joining sentences can grant on
the wrong figure.

**4. Two numbers means no number.** A rule whose sentence holds more than one figure does not
pick one.

**5. Undetermined is never met.** A missing figure is `None`, and `None` blocks an automated grant.

**6. Quote the evidence, and check the quote.** A quote shows the reader exactly what the rule read.
A test that checks the quote checks the reason, not only the result.

**7. Test against the formats that really appear.** Decimals, abbreviations, ranges, zeros and
graded listings each broke a rule that worked on clean examples.

## Part 10. What is unresolved

1. **Street abbreviations still cost an officer's time.** "The rear boundary on Mill St. is 1.4 m
   away." splits after "St.", the keyword and the figure land in different pieces, and C1 is
   undetermined. That is the safe direction, chosen on purpose, but it is a cost.
2. **The one-number rule costs time too.** "At No. 14 the setback is 1.4 m" goes to a person
   (Part 5.4). Telling which number belongs to which word needs a parser, and a parser's mistakes
   would need measuring before it decided anything.
3. **Ranges always go to a person.** "between 1.2 and 1.6 m" meets the 1.0 m minimum at every
   point, but it is undetermined, because the rule refuses to choose. Whether a range can be
   decided automatically, and on which end, needs a planning officer's view.
4. **Units other than metres.** "4 ft 6 in" is not read. An application in feet goes to a person.
5. **Numbers written as words.** "one point four metres" is not read.
6. **The criteria are invented.** A real authority's rules, and its view on how strictly to read an
   applicant's wording, need sign-off from its planning and legal teams.

## Glossary

| Term | Plain meaning | Explained in |
|---|---|---|
| Abbreviation | A shortened word ending in a full stop, such as "approx." or "St." | Part 4 |
| Alternation | In a regular expression, `(?:A\|B)`: match A or B as whole words | Part 6.2 |
| Ambiguous sentence | A sentence holding more than one number, so a rule cannot tell which is its figure | Part 5 |
| Asymmetric error | Two possible mistakes whose costs differ, so the code favours the cheaper one | Part 4.3 |
| Character class | In a regular expression, `[...]`: match any one of the characters inside | Part 6.2 |
| Criterion | One of the five published rules, C1 to C5 | Running example |
| Decimal point | The full stop inside a number such as 1.4, with a digit on both sides | Part 3.3 |
| Grounding | Recording the exact sentence a finding relied on, quoted from the application | Part 7 |
| Keyword | The word a rule looks for to find its sentence, such as "setback" | Part 2.1 |
| Listed building | A building protected for its history, graded I, II* or II | Part 6.2 |
| Measurement | A number followed by a unit: "m", "metre" or "meter" | Part 2.1 |
| One-number rule | A measurement rule reads only from a sentence with exactly one number in it | Part 5.3 |
| Quote | The sentence a finding relied on, copied exactly | Part 7.1 |
| Regular expression | A pattern language for matching text | Part 1.1 |
| Setback | How far a building stands from the edge of its plot | Running example |
| Sentence splitter | The code that cuts an application into sentences | Part 3 |
| Tokeniser | Any code that cuts text into pieces | Part 3.1 |
| Undetermined | A rule's result when it cannot find its figure: `None`, never treated as met | Part 2.3 |
