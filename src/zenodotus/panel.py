"""No-context reviewer panel (scaffold).

N independent reviewers, each blind to the others and to internal context, judge
the parts deterministic gates cannot: coherence, naming, scope, leakage,
usefulness, doc quality. Provider-agnostic; default provider Anthropic Claude.
Returns per-reviewer verdicts + a consensus. Every panel finding NOT already
caught by a deterministic gate MUST be recorded via discovery_log.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReviewerVerdict:
    reviewer: str
    go: bool
    findings: list[dict]
    rationale: str


def review(path: str, n_reviewers: int = 3) -> list[ReviewerVerdict]:
    raise NotImplementedError("reviewer panel — see repo issues")
