"""Discovery log — the panel's justification record.

Every finding the reviewer panel surfaces that the deterministic gates did NOT
catch is appended here. This log is the evidence base for whether Zenodotus
earns its keep, and it GATES the public-flip / publish decision (see
docs/CONCEPT.md). Kept deliberately simple and append-only (JSONL).

NOTE: the timestamp is injected by the caller so the module stays testable and
deterministic; do not read the clock here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CATEGORIES = (
    "coherence", "naming", "scope", "leakage", "usefulness", "doc-quality", "other",
)


@dataclass
class Discovery:
    repo: str
    finding: str
    category: str
    severity: str  # blocker | major | minor
    reviewer: str
    rationale: str
    at: str  # ISO-8601, supplied by caller
    caught_by: str = "panel"
    missed_by_deterministic: bool = True
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category: {self.category!r} (expected one of {CATEGORIES})")


def append(log_path: str | Path, discovery: Discovery) -> None:
    """Append one discovery as a JSONL line."""
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(discovery), sort_keys=True) + "\n")


def load(log_path: str | Path) -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
