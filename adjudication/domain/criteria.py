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
_SENT = re.compile(r"(?<!\d)[.;\n](?!\d)")


def _sentences(text: str) -> list[str]:
    return _SENT.split(text)


@dataclass(frozen=True)
class RuleResult:
    satisfied: bool | None
    rationale: str


def _first_measure(text: str, near: str) -> float | None:
    """Measurement in the same sentence as the keyword. Not the first number in the text."""
    for sent in _sentences(text):
        if near.lower() in sent.lower():
            m = _M.search(sent)
            if m:
                return float(m.group(1))
    return None


def check_setback(text: str) -> RuleResult:
    v = _first_measure(text, "setback") or _first_measure(text, "boundary")
    if v is None:
        return RuleResult(None, "no boundary setback stated")
    return RuleResult(v >= 1.0, f"stated setback {v} m against minimum 1.0 m")


def check_height(text: str) -> RuleResult:
    v = _first_measure(text, "height")
    if v is None:
        return RuleResult(None, "no height stated")
    return RuleResult(v <= 4.0, f"stated height {v} m against maximum 4.0 m")


def check_coverage(text: str) -> RuleResult:
    for sent in _sentences(text):
        if "coverage" in sent.lower():
            m = _PCT.search(sent)
            if m:
                v = float(m.group(1))
                return RuleResult(v <= 50.0, f"stated coverage {v}% against maximum 50%")
    return RuleResult(None, "no site coverage stated")


def check_flood(text: str) -> RuleResult:
    if re.search(r"flood zone\s*3", text, re.I):
        has = bool(re.search(r"flood risk assessment|FRA\b", text, re.I))
        return RuleResult(has, "flood zone 3: FRA " + ("present" if has else "absent"))
    return RuleResult(True, "not in flood zone 3")


def check_heritage(text: str) -> RuleResult:
    if re.search(r"listed building|grade [I|II]", text, re.I):
        has = bool(re.search(r"conservation officer", text, re.I))
        return RuleResult(has, "listed: conservation consultation "
                               + ("recorded" if has else "absent"))
    return RuleResult(True, "not listed")


RULES = {
    "C1": check_setback, "C2": check_height, "C3": check_coverage,
    "C4": check_flood, "C5": check_heritage,
}


def evaluate(text: str, evidence: dict[str, list[Evidence]] | None = None) -> list[Finding]:
    ev = evidence or {}
    out: list[Finding] = []
    for code, rule in RULES.items():
        r = rule(text)
        out.append(Finding(criterion_code=code, satisfied=r.satisfied,
                           rationale=r.rationale, evidence=list(ev.get(code, []))))
    return out
