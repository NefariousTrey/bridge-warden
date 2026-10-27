"""Plain data types shared by the checker."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

ACTIONS = ("create_order", "payout", "refund")
ALLOW, HOLD, BLOCK = "allow", "hold", "block"
_RANK = {ALLOW: 0, HOLD: 1, BLOCK: 2}


def worst(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass
class ProposedAction:
    """Something an AI agent wants to do with money. Nothing runs until the checker says so."""
    action: str                      # create_order | payout | refund
    amount: str                      # decimal string, e.g. "12.50"
    currency: str = "USD"
    payee: str = ""                  # who gets the money (email for payouts, merchant/customer for orders)
    description: str = ""            # the agent's own words about why
    agent_id: str = "demo-agent"
    capture_id: Optional[str] = None  # refunds only: which PayPal capture to refund
    action_id: str = field(default_factory=lambda: "act-" + uuid.uuid4().hex[:10])
    proposed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProposedAction":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class Finding:
    rule: str
    severity: str   # allow (info) | hold | block
    reason: str     # plain English, for the owner
    points: int = 0


@dataclass
class Verdict:
    action_id: str
    verdict: str
    risk_score: int
    findings: list = field(default_factory=list)
    ai_scam_probability: float = 0.0

    @property
    def reasons(self) -> list:
        return [f.reason for f in self.findings if f.severity != ALLOW] or ["Nothing looks risky."]

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "verdict": self.verdict,
            "risk_score": self.risk_score,
            "ai_scam_probability": round(self.ai_scam_probability, 3),
            "reasons": self.reasons,
            "findings": [asdict(f) for f in self.findings],
        }
