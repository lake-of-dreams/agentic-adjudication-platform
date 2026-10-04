"""Criteria rules. No model anywhere near this.

Auditors re-perform this arithmetic by hand and it has to match, so anything a
rule can settle is settled by a rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Criterion, Evidence, Finding

CRITERIA: dict[str, Criterion] = {
    "C1": Criterion("C1", "Boundary setback",
                    "Structure must be set back at least 1.0 m from any boundary."),
    "C2": Criterion("C2", "Maximum height",
                    "Structure must not exceed 4.0 m measured from natural ground level."),
    "C3": Criterion("C3", "Site coverage",
                    "Total built coverage must not exceed 50% of the plot area."),
    "C4": Criterion("C4", "Flood zone",
                    "Sites in flood zone 3 require a flood risk assessment.",
                    mandatory=True),
    "C5": Criterion("C5", "Heritage",
                    "Listed buildings require conservation officer consultation.",
                    mandatory=True),
}

_M = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|metre|meter)s?\b", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Sentence split that does not break inside a decimal. This used to split on
# "." and ate the decimal: "setback is 1.4 m" became "setback is 1" + "4 m", so
# the rule reported "no setback stated" for an application that stated one.
# First smoke test caught it. ADR-0005.
#
# The first fix refused to split on any full stop next to a digit, so "flood
# zone 3. No assessment" stayed one sentence and a sentence ending in a number
# swallowed the next one. A decimal point has a digit on both sides; that is
# the only place not to split.
_SENT = re.compile(r"(?<!\d)[.;\n]|[.;\n](?!\d)")


def _sentences(text: str) -> list[str]:
    return _SENT.split(text)


@dataclass(frozen=True)
class RuleResult:
    satisfied: bool | None
    rationale: str
    # The sentence the rule relied on, quoted exactly from the application. A
    # measured criterion with no quote cannot carry an automated grant.
    quote: str | None = None
    # True when the rule settled the criterion by searching the whole text and
    # finding nothing that triggers it, e.g. no mention of flood zone 3. There
    # is no sentence to quote for an absence; the search itself is the basis.
    absence: bool = False


def _sentence_with(text: str, pattern: re.Pattern) -> str | None:
    for sent in _sentences(text):
        if pattern.search(sent):
            return sent.strip()
    return None


def _first_measure(text: str, near: str) -> tuple[float, str] | None:
    """Measurement in the same sentence as the keyword. Not the first number in the text.

    Returns the value and the sentence it came from, so the finding can quote it.
    """
    for sent in _sentences(text):
        if near.lower() in sent.lower():
            m = _M.search(sent)
            if m:
                return float(m.group(1)), sent.strip()
    return None


def check_setback(text: str) -> RuleResult:
    # Explicit None checks. `a or b` treated a stated setback of 0 m as missing
    # and fell through to the next keyword.
    hit = _first_measure(text, "setback")
    if hit is None:
        hit = _first_measure(text, "boundary")
    if hit is None:
        return RuleResult(None, "no boundary setback stated")
    v, quote = hit
    return RuleResult(v >= 1.0, f"stated setback {v} m against minimum 1.0 m", quote)


def check_height(text: str) -> RuleResult:
    hit = _first_measure(text, "height")
    if hit is None:
        return RuleResult(None, "no height stated")
    v, quote = hit
    return RuleResult(v <= 4.0, f"stated height {v} m against maximum 4.0 m", quote)


def check_coverage(text: str) -> RuleResult:
    for sent in _sentences(text):
        if "coverage" in sent.lower():
            m = _PCT.search(sent)
            if m:
                v = float(m.group(1))
                return RuleResult(v <= 50.0, f"stated coverage {v}% against maximum 50%",
                                  sent.strip())
    return RuleResult(None, "no site coverage stated")


_FLOOD3 = re.compile(r"flood zone\s*3", re.I)
_FRA = re.compile(r"flood risk assessment|\bFRA\b", re.I)
# "grade [I|II]" was a character class: it matched "grade |" and any word
# starting with I, and only by luck caught "Grade II". Alternation, and the
# starred grade.
_LISTED = re.compile(r"listed building|\bgrade\s+(?:I|II\*?)(?![\w*])", re.I)
_CONSERVATION = re.compile(r"conservation officer", re.I)


def check_flood(text: str) -> RuleResult:
    trigger = _sentence_with(text, _FLOOD3)
    if trigger is None:
        return RuleResult(True, "no mention of flood zone 3 anywhere in the application",
                          absence=True)
    fra = _sentence_with(text, _FRA)
    if fra is None:
        return RuleResult(False, "flood zone 3: flood risk assessment absent", trigger)
    return RuleResult(True, "flood zone 3: flood risk assessment present", fra)


def check_heritage(text: str) -> RuleResult:
    trigger = _sentence_with(text, _LISTED)
    if trigger is None:
        return RuleResult(True, "no mention of a listed building anywhere in the application",
                          absence=True)
    consult = _sentence_with(text, _CONSERVATION)
    if consult is None:
        return RuleResult(False, "listed: conservation consultation absent", trigger)
    return RuleResult(True, "listed: conservation consultation recorded", consult)


RULES = {
    "C1": check_setback, "C2": check_height, "C3": check_coverage,
    "C4": check_flood, "C5": check_heritage,
}


def evaluate(text: str, evidence: dict[str, list[Evidence]] | None = None,
             document_id: str = "application") -> list[Finding]:
    """Apply every rule. Each finding quotes the sentence it relied on.

    `evidence` adds citations from other documents to particular criteria.
    """
    ev = evidence or {}
    out: list[Finding] = []
    for code, rule in RULES.items():
        r = rule(text)
        cites = list(ev.get(code, []))
        if r.quote:
            cites.insert(0, Evidence(document_id, f"sentence containing: {r.quote[:40]}", r.quote))
        out.append(Finding(criterion_code=code, satisfied=r.satisfied,
                           rationale=r.rationale, evidence=cites, absence_checked=r.absence))
    return out
