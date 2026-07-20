"""No-context reviewer panel.

N independent reviewers, each blind to the others and to internal context, judge
the parts deterministic gates cannot: coherence, naming, scope, leakage,
usefulness, doc quality. Provider-agnostic; the default provider is Anthropic
Claude (latest model). Returns per-reviewer verdicts + a consensus.

Every panel finding NOT already caught by a deterministic gate is recorded via
``discovery_log.append`` with ``missed_by_deterministic=True`` — this log is the
load-bearing evidence base for the prove-itself gate (docs/CONCEPT.md).

No live LLM calls happen in tests: the provider is injectable, and the default
``AnthropicProvider`` imports the ``anthropic`` SDK lazily so importing this
module (and running the suite with a stub/replay provider) needs no API key.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import discovery_log
from .discovery_log import CATEGORIES, Discovery

# Default provider model. Overridable via env; the issue calls for "latest model".
DEFAULT_MODEL = os.environ.get("ZENODOTUS_MODEL", "claude-opus-4-8")

# The rubric each no-context reviewer answers. Deliberately framed for an
# outsider with zero internal context — that blindness is the whole point.
REVIEWER_RUBRIC = """\
You are an independent open-source release reviewer. You have NO internal context
about this project, its authors, or its organization — judge it exactly as an
outsider encountering the repository for the first time would.

Deterministic tools already checked license presence, community files, secret
leakage, and packaging hygiene. Do NOT re-report those. Judge only what a linter
cannot:

- coherence   — is the README/docs coherent to an outsider with zero context?
- naming      — is the naming and scope sensible (one thing done well)?
- scope       — is scope focused, not a grab-bag?
- leakage     — internal/proprietary leakage that is NOT a secret: internal
                hostnames, dead links, employee/competitor names, sarcastic or
                unprofessional comments, TODOs referencing private systems.
- usefulness  — is this actually useful and finished enough to exist publicly?
- doc-quality — are the docs accurate, complete, and honest?

Return a go/no-go verdict. Any BLOCKER finding means no-go. Report each finding
with a category (one of: coherence, naming, scope, leakage, usefulness,
doc-quality, other) and a severity (blocker, major, minor)."""

# JSON schema the provider is asked to satisfy (structured output).
VERDICT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "go": {"type": "boolean"},
        "rationale": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                    "rationale": {"type": "string"},
                },
                "required": ["finding", "category", "severity", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["go", "rationale", "findings"],
    "additionalProperties": False,
}


@dataclass
class ReviewerVerdict:
    reviewer: str
    go: bool
    findings: list[dict]
    rationale: str


@dataclass
class PanelReview:
    """Aggregate result of a panel run."""

    verdicts: list[ReviewerVerdict]
    consensus_go: bool
    discoveries: list[Discovery] = field(default_factory=list)


class Provider(Protocol):
    """A reviewer backend. Given the gathered repo context, returns one verdict.

    Implementations MUST NOT be given internal context beyond ``context`` (the
    repo's own public files) — reviewers are no-context by design.
    """

    def review(self, reviewer_id: str, context: str) -> dict:
        """Return ``{"go": bool, "rationale": str, "findings": [ {...}, ... ]}``."""
        ...


class AnthropicProvider:
    """Default provider — Anthropic Claude, latest model. Lazily imports the SDK."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - only hit without the SDK
                raise RuntimeError(
                    "The 'anthropic' package is required for the default provider. "
                    "Install with `pip install \"zenodotus[llm]\"`, or pass a custom "
                    "provider to review()."
                ) from exc
            # anthropic.Anthropic() resolves ANTHROPIC_API_KEY (or an ant profile).
            self._client = anthropic.Anthropic(api_key=self._api_key) if self._api_key \
                else anthropic.Anthropic()
        return self._client

    def review(self, reviewer_id: str, context: str) -> dict:  # pragma: no cover - needs live API
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=REVIEWER_RUBRIC,
            output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            messages=[{
                "role": "user",
                "content": f"Reviewer id: {reviewer_id}\n\nRepository under review:\n\n{context}",
            }],
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)


# --- context gathering ------------------------------------------------------- #

# Public files an outsider would actually read. Bounded so context stays small.
_CONTEXT_FILES = (
    "README.md", "README.rst", "README",
    "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md",
    "docs/CONCEPT.md", "docs/POSITIONING.md",
    "pyproject.toml", "setup.py", "setup.cfg",
)
_MAX_FILE_CHARS = 8000


def gather_context(path: str) -> str:
    """Collect the repo's public-facing files into one bounded review context."""
    root = Path(path)
    parts: list[str] = []
    # A file tree gives reviewers a sense of scope.
    tree = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    )
    parts.append("## File tree\n" + "\n".join(tree[:200]))

    for rel in _CONTEXT_FILES:
        fp = root / rel
        if fp.is_file():
            body = fp.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_CHARS]
            parts.append(f"## {rel}\n{body}")
    return "\n\n".join(parts)


# --- consensus --------------------------------------------------------------- #

def any_blocker_no_go(verdicts: list[ReviewerVerdict]) -> bool:
    """Default consensus: go unless any reviewer said no-go or raised a blocker."""
    if not verdicts:
        return False
    for v in verdicts:
        if not v.go:
            return False
        if any(f.get("severity") == "blocker" for f in v.findings):
            return False
    return True


# --- deterministic dedupe ---------------------------------------------------- #

# Which finding categories a deterministic gate can plausibly cover. In the real
# pipeline the panel only runs once the floor has PASSED, so every gate passed
# and nothing here matches — all findings become panel-only discoveries. This
# mapping only bites when the panel is run alongside FAILING gates (e.g. shadow
# mode), where a leak the secret scanner already caught should not be re-logged.
_GATE_COVERS: dict[str, set[str]] = {
    "no_secrets": {"leakage"},
}


def _deterministically_caught(finding: dict, gate_results) -> bool:
    if not gate_results:
        return False
    category = finding.get("category")
    for gate in gate_results:
        # a gate only "catches" something when it actually FAILED (not skipped)
        failed = (not getattr(gate, "passed", False)) and (not getattr(gate, "skipped", False))
        if failed and category in _GATE_COVERS.get(getattr(gate, "name", ""), set()):
            return True
    return False


# --- panel ------------------------------------------------------------------- #

def review(
    path: str,
    n_reviewers: int = 3,
    *,
    provider: Provider | None = None,
    consensus: Callable[[list[ReviewerVerdict]], bool] | None = None,
    gate_results=None,
    log_path: str | Path | None = None,
    at: str | None = None,
    repo_name: str | None = None,
) -> PanelReview:
    """Run ``n_reviewers`` no-context reviewers over ``path`` and aggregate.

    Each reviewer is blind to the others (they receive only the gathered public
    context, independently). Every finding not already caught by a deterministic
    gate is appended to the discovery log at ``log_path`` (if given) with
    ``missed_by_deterministic=True``.

    ``at`` is the ISO-8601 timestamp stamped onto discovery-log entries; the
    caller supplies it so the log stays deterministic (discovery_log never reads
    the clock). Required whenever ``log_path`` is set.
    """
    if provider is None:
        provider = AnthropicProvider()
    if consensus is None:
        consensus = any_blocker_no_go
    if log_path is not None and at is None:
        raise ValueError("`at` (ISO-8601 timestamp) is required when writing a discovery log")
    repo = repo_name or Path(path).name

    context = gather_context(path)

    verdicts: list[ReviewerVerdict] = []
    for i in range(n_reviewers):
        reviewer_id = f"reviewer-{i + 1}"
        raw = provider.review(reviewer_id, context)
        verdicts.append(ReviewerVerdict(
            reviewer=reviewer_id,
            go=bool(raw.get("go", False)),
            findings=list(raw.get("findings", [])),
            rationale=str(raw.get("rationale", "")),
        ))

    # Record panel-only discoveries (things the deterministic floor missed).
    discoveries: list[Discovery] = []
    for v in verdicts:
        for f in v.findings:
            if _deterministically_caught(f, gate_results):
                continue
            category = f.get("category", "other")
            if category not in CATEGORIES:
                category = "other"
            d = Discovery(
                repo=repo,
                finding=str(f.get("finding", "")),
                category=category,
                severity=str(f.get("severity", "minor")),
                reviewer=v.reviewer,
                rationale=str(f.get("rationale", "")),
                at=at or "",
                caught_by="panel",
                missed_by_deterministic=True,
            )
            discoveries.append(d)
            if log_path is not None:
                discovery_log.append(log_path, d)

    return PanelReview(
        verdicts=verdicts,
        consensus_go=consensus(verdicts),
        discoveries=discoveries,
    )
