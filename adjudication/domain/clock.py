"""Statutory determination windows.

Legal deadlines, so they sit in the domain layer rather than in config next to
the SLOs. AUTOMATION_BUDGET holds part of the window back for the officer.
Without it an escalation just hands someone an impossible deadline.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .model import RiskTier

# calendar days
STATUTORY_DAYS: dict[RiskTier, int] = {
    RiskTier.ROUTINE: 14,
    RiskTier.STANDARD: 28,
    RiskTier.COMPLEX: 56,
}

# How much of the window the automated path may burn before handing over. The
# rest belongs to the officer.
AUTOMATION_BUDGET = 0.40


@dataclass(frozen=True)
class Clock:
    received_at: dt.datetime
    risk_tier: RiskTier

    @property
    def statutory_deadline(self) -> dt.datetime:
        return self.received_at + dt.timedelta(days=STATUTORY_DAYS[self.risk_tier])

    @property
    def automation_deadline(self) -> dt.datetime:
        days = STATUTORY_DAYS[self.risk_tier] * AUTOMATION_BUDGET
        return self.received_at + dt.timedelta(days=days)

    def human_headroom(self, now: dt.datetime) -> dt.timedelta:
        return self.statutory_deadline - now

    def must_hand_over(self, now: dt.datetime) -> bool:
        return now >= self.automation_deadline

    def breached(self, now: dt.datetime) -> bool:
        return now > self.statutory_deadline
