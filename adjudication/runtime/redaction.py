"""Reversible PII redaction, typed placeholders.

[PERSON_1] rather than [REDACTED], so downstream reasoning about who is who
still works. Substitution runs right to left, see redact().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("PHONE", re.compile(r"\b(?:\+?\d{1,3}[ -]?)?(?:\d[ -]?){9,12}\d\b")),
    ("POSTCODE", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")),
    ("NINO", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")),
    ("PERSON", re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")),
]


@dataclass
class Redaction:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)

    def reidentify(self, text: str) -> str:
        """Restore originals. Longest first, or [PERSON_1] eats the prefix of
        [PERSON_10]."""
        for ph in sorted(self.mapping, key=len, reverse=True):
            text = text.replace(ph, self.mapping[ph])
        return text


def redact(text: str) -> Redaction:
    spans: list[tuple[int, int, str, str]] = []
    for label, pat in PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), label, m.group()))

    # drop overlaps, earliest then longest wins
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str, str]] = []
    last_end = -1
    for s in spans:
        if s[0] >= last_end:
            kept.append(s)
            last_end = s[1]

    # number in document order, so placeholders are stable run to run
    counters: dict[str, int] = {}
    numbered: list[tuple[int, int, str, str]] = []
    for start, end, label, original in kept:
        counters[label] = counters.get(label, 0) + 1
        numbered.append((start, end, f"[{label}_{counters[label]}]", original))

    # right to left, otherwise the offsets we already worked out go stale
    out = text
    mapping: dict[str, str] = {}
    for start, end, placeholder, original in sorted(numbered, key=lambda s: s[0], reverse=True):
        out = out[:start] + placeholder + out[end:]
        mapping[placeholder] = original
    return Redaction(out, mapping)
