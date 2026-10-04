"""Append-only audit log, SHA-256 hash chain.

Each entry hashes the previous one, so edits and deletions break verification.
That only makes tampering visible. Stopping it needs a write-once store
underneath.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    case_id: str
    actor: str                 # "system:<node>" or "officer:<id>"
    action: str
    detail: dict
    at: str
    prev_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        payload = {
            "seq": self.seq, "case_id": self.case_id, "actor": self.actor,
            "action": self.action, "detail": self.detail, "at": self.at,
            "prev_hash": self.prev_hash,
        }
        # sort_keys, or dict ordering changes the hash
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class TamperDetected(RuntimeError):
    pass


@dataclass
class AuditLog:
    entries: list[AuditEntry] = field(default_factory=list)

    def append(self, case_id: str, actor: str, action: str, detail: dict | None = None) -> AuditEntry:
        prev = self.entries[-1].entry_hash if self.entries else GENESIS
        e = AuditEntry(
            seq=len(self.entries), case_id=case_id, actor=actor, action=action,
            detail=detail or {}, at=dt.datetime.now(dt.UTC).isoformat(),
            prev_hash=prev)
        e = AuditEntry(**{**asdict(e), "entry_hash": e.compute_hash()})
        self.entries.append(e)
        return e

    def verify(self) -> bool:
        prev = GENESIS
        for e in self.entries:
            if e.prev_hash != prev:
                raise TamperDetected(f"chain broken at seq {e.seq}: prev_hash mismatch")
            if e.compute_hash() != e.entry_hash:
                raise TamperDetected(f"entry {e.seq} content altered")
            prev = e.entry_hash
        return True

    def for_case(self, case_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.case_id == case_id]

    def reconstruct(self, case_id: str) -> str:
        lines = [f"Case {case_id}: {len(self.for_case(case_id))} entries"]
        for e in self.for_case(case_id):
            lines.append(f"  [{e.seq:>3}] {e.at} {e.actor:<26} {e.action}")
            for k, v in e.detail.items():
                lines.append(f"         {k}: {v}")
        return "\n".join(lines)
