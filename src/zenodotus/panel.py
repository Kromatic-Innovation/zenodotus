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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from . import discovery_log, fileset, isolation
from .discovery_log import CATEGORIES, Discovery

# Default provider model. The two rungs are split (issue #86) so review()'s
# `model=` precedence can distinguish "the ZENODOTUS_MODEL env var" from "the
# library's built-in default" — collapsing them into one `os.environ.get(...,
# default)` expression would make those two rungs indistinguishable. The
# literal default is unchanged: still ``claude-opus-4-8`` when the env is unset.
_ENV_MODEL = os.environ.get("ZENODOTUS_MODEL")
DEFAULT_MODEL = _ENV_MODEL or "claude-opus-4-8"


def _iso_now() -> str:
    """Real ISO-8601 UTC timestamp for the `at` fallback in review() below.

    Only used to stamp DeniedAttempt.at when a caller runs review() without
    `log_path`/`at` (docs/PANEL_VERDICT_SPEC.md §1.3 pins ``"at": "<ISO-8601>"``,
    not an empty string). The discovery log itself is unaffected — it still
    requires an explicit `at` from the caller so it stays deterministic
    (discovery_log never reads the clock; see review()'s guard clause).

    Matches ``cli._utcnow_iso()``'s shape exactly (seconds precision, ``Z``
    suffix) so ``isolation.denied[].at`` reads identically whether it came
    from the CLI or a library caller — a sibling repo (panelist) implements
    the same envelope against this timestamp field.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# The rubric each no-context reviewer answers. Deliberately framed for an
# outsider with zero internal context — that blindness is the whole point.
REVIEWER_RUBRIC = """\
You are an independent open-source release reviewer. You have NO internal context
about this project, its authors, or its organization — judge it exactly as an
outsider encountering the repository for the first time would.

You are reviewing a PRE-PUBLISH RELEASE CANDIDATE, not the live published
artifact. This tree is on `develop`/`main` and has NOT been published to its
registry (PyPI/npm/crates.io/…) yet; the version currently live in that registry
is the PREVIOUS release and will ALWAYS lag this candidate until a human cuts the
tag. That lag is the entire reason a pre-publish gate exists — it is the expected,
structural state of any release candidate reviewed before publish, not a defect
to fix in the candidate. Assess this tree as the artifact that is ABOUT TO
REPLACE the current live version, not as an audit of today's live version against
the tree.

Therefore, do NOT flag a mismatch between the live registry and this candidate
tree as a release-blocker. A CHANGELOG entry that reads as already-shipped, a
README documenting the about-to-ship version's behavior, or a `version` the
registry has not caught up to yet are all EXPECTED pre-publish states that resolve
automatically on publish. If a finding's ONLY basis is "the live registry has not
been updated to match this candidate yet", report it — if at all — as an
informational, `minor`-severity RELEASE-DAY CHECKLIST note (a reminder for whoever
cuts the tag), NEVER a `blocker` and never a reviewer no-go. Only treat it as a
real defect if it would STILL be wrong AFTER this candidate is published — e.g. a
CHANGELOG date wrong even for a same-day tag, a feature that is genuinely broken,
or a doc describing behavior the candidate itself does not implement.

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

Grade every finding by severity, and reserve blocking for genuine blockers:

- blocker — a real release-blocker: something that would genuinely embarrass or
            harm an outsider (e.g. leaked internal context, a feature promised
            but not shipped, a README an outsider truly cannot follow). Blocking
            is the exception, not the default posture.
- major / minor — advisory findings worth raising that should WARN, not block
            (coherence nits, naming/scope observations, doc-quality gaps).

Return a `go` boolean plus severity-graded findings. Set `go: false` ONLY if you
would genuinely block the release (a blocker-level problem); advisory findings
alone keep `go: true` and simply warn. Report each finding with a category (one
of: coherence, naming, scope, leakage, usefulness, doc-quality, other) and a
severity (blocker, major, minor)."""

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
                    "severity": {
                        "type": "string",
                        "enum": ["blocker", "major", "minor"],
                    },
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
    # Effective tool identifiers this reviewer actually had (issue #79 /
    # docs/PANEL_VERDICT_SPEC.md §1.3). Empty by default — fully isolated.
    tools: list[str] = field(default_factory=list)


@dataclass
class PanelReview:
    """Aggregate result of a panel run."""

    verdicts: list[ReviewerVerdict]
    consensus_go: bool
    discoveries: list[Discovery] = field(default_factory=list)
    # docs/PANEL_VERDICT_SPEC.md §1.3 isolation record: `tools` is the union of
    # every reviewer's effective tool set, `denied` is every attempted-but-
    # blocked tool declaration across the panel. Empty/empty is the default,
    # fully-isolated posture.
    isolation: dict = field(default_factory=lambda: {"tools": [], "denied": []})


class Provider(Protocol):
    """A reviewer backend. Given the gathered repo context, returns one verdict.

    Implementations MUST NOT be given internal context beyond ``context`` (the
    repo's own public files) — reviewers are no-context by design.

    ``tools`` is the list of tool declarations (provider-format dicts with at
    least a ``name`` key) this call is actually permitted to offer the model —
    already filtered through :mod:`zenodotus.isolation` by the caller. A
    provider that routes its tool declarations through this ``tools``
    parameter (as the shipped ``AnthropicProvider`` does) MUST NOT offer any
    tool outside this list; it is the enforcement boundary for the no-context
    guarantee (issue #79) for those providers. The guarantee is structural
    only up to that boundary: the isolation envelope can see nothing a
    third-party ``Provider`` implementation declares outside ``tools`` (e.g.
    tools it wires up itself inside its own ``review()`` body) — such a run
    would still report ``{"tools": [], "denied": []}``. Providers are
    responsible for actually routing every tool declaration through this
    parameter.
    """

    def review(
        self, reviewer_id: str, context: str, *, tools: list[dict] | None = None
    ) -> dict:
        """Return ``{"go": bool, "rationale": str, "findings": [ {...}, ... ]}``."""
        ...


class AnthropicProvider:
    """Default provider — Anthropic Claude, latest model. Lazily imports the SDK.

    ``requested_tools`` is the tool declarations this provider WOULD LIKE to
    offer the model (Anthropic API tool-schema dicts) — empty by default, so
    the default panel run never even attempts to declare a tool. Whatever it
    requests still passes through the caller's :mod:`zenodotus.isolation`
    policy in :func:`review`; only what survives that filter is ever sent to
    the API via the ``tools`` kwarg.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        requested_tools: list[dict] | None = None,
    ):
        self.model = model
        self._api_key = api_key
        self._client = None
        self.requested_tools = list(requested_tools or [])

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - only hit without the SDK
                raise RuntimeError(
                    "The 'anthropic' package is required for the default provider. "
                    'Install with `pip install "zenodotus[llm]"`, or pass a custom '
                    "provider to review()."
                ) from exc
            # anthropic.Anthropic() resolves ANTHROPIC_API_KEY (or an ant profile).
            self._client = (
                anthropic.Anthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.Anthropic()
            )
        return self._client

    def review(
        self, reviewer_id: str, context: str, *, tools: list[dict] | None = None
    ) -> dict:
        client = self._get_client()
        kwargs = {"tools": tools} if tools else {}
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=REVIEWER_RUBRIC,
            output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": f"Reviewer id: {reviewer_id}\n\nRepository under review:\n\n{context}",
                }
            ],
            **kwargs,
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)


# --- context gathering ------------------------------------------------------- #

# Public files an outsider would actually read. Bounded so context stays small.
# The LICENSE body is included (issue #30 defect 3): omitting it makes reviewers
# raise license-mismatch/uncertainty findings they could otherwise resolve.
_CONTEXT_FILES = (
    "README.md",
    "README.rst",
    "README",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENCE",
    "COPYING",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "docs/CONCEPT.md",
    "docs/POSITIONING.md",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
)
# Generous per-file cap (issue #30 defect 1). The old 8,000-char cap sliced long
# but complete READMEs mid-word, so reviewers mis-flagged them as "unfinished".
# We keep a bound so context stays sane, but raise it well past any real README
# and — if we ever do hit it — annotate explicitly that the source is complete.
_MAX_FILE_CHARS = 200_000


def gather_context(path: str) -> str:
    """Collect the repo's public-facing files into one bounded review context."""
    root = Path(path)
    parts: list[str] = []
    # A file tree gives reviewers a sense of scope. Enumerate the files that would
    # actually ship (git-tracked, respecting .gitignore) via the shared helper, so
    # untracked working-tree noise never presents as shipped content (issue #30
    # defect 2) and this stays in lockstep with leakcheck's enumeration (#68).
    files = fileset.shippable_files(root)
    tree = sorted(files)
    parts.append("## File tree\n" + "\n".join(tree[:200]))

    for rel in _CONTEXT_FILES:
        fp = root / rel
        if fp.is_file():
            raw = fp.read_text(encoding="utf-8", errors="replace")
            body = raw[:_MAX_FILE_CHARS]
            if len(raw) > _MAX_FILE_CHARS:
                omitted = len(raw) - _MAX_FILE_CHARS
                body += (
                    f"\n\n[zenodotus: {omitted} more character(s) omitted here to keep "
                    "the review context bounded — the source file is COMPLETE, not "
                    "truncated or unfinished. Do not report it as incomplete.]"
                )
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


# --- three-state verdict projection ------------------------------------------ #

# The shared three-state verdict vocabulary (docs/PANEL_VERDICT_SPEC.md §1).
PASS, WARN, BLOCK = "pass", "warn", "block"


def panel_verdict(review: PanelReview) -> str:
    """Project a completed panel run onto the three-state verdict `pass|warn|block`.

    This is the panel's own contribution to the aggregate verdict, before any
    caller-side policy (the deterministic floor, `--fail-on`, or shadow mode) is
    applied. It implements the severity→state mapping of
    ``docs/PANEL_VERDICT_SPEC.md`` §1.1/§1.2:

    - ``consensus_go is False`` (a reviewer no-go OR any blocker-severity finding
      — the two the default consensus collapses) → ``block``. Per §1.1 a
      per-reviewer no-go is treated as equivalent to a blocker for the aggregate.
    - ``consensus_go is True`` but advisory findings exist (``major``/``minor``)
      → ``warn``.
    - No findings at all → ``pass``.
    """
    if not review.consensus_go:
        return BLOCK
    if any(v.findings for v in review.verdicts):
        return WARN
    return PASS


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
        failed = (not getattr(gate, "passed", False)) and (
            not getattr(gate, "skipped", False)
        )
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
    reviewer_tools: dict | list[str] | None = None,
    model: str | None = None,
) -> PanelReview:
    """Run ``n_reviewers`` no-context reviewers over ``path`` and aggregate.

    Each reviewer is blind to the others (they receive only the gathered public
    context, independently). Every finding not already caught by a deterministic
    gate is appended to the discovery log at ``log_path`` (if given) with
    ``missed_by_deterministic=True``.

    ``model`` (issue #86) states the Claude model for the panel at the call site,
    mirroring how ``reviewer_tools`` is resolved here and applied at the provider
    boundary — the :class:`Provider` protocol deliberately knows nothing about
    models, so this configures the default :class:`AnthropicProvider` rather than
    threading a model through the protocol. Precedence, highest first:

    1. an explicit ``model=`` kwarg,
    2. an explicitly passed ``provider=``'s own configured model,
    3. the ``ZENODOTUS_MODEL`` environment variable,
    4. :data:`DEFAULT_MODEL` (``"claude-opus-4-8"``).

    Passing **both** ``model=`` and a caller-constructed ``provider=`` raises
    ``ValueError``: a caller-supplied provider owns its own model, and the
    protocol exposes no model concept, so ``model=`` cannot be reliably applied
    to an arbitrary provider — refusing the combination is louder than silently
    honouring it only for :class:`AnthropicProvider`. To run a specific model on
    the default provider, pass ``model=`` without ``provider=``; to control the
    model on a custom provider, configure it on that provider before passing it.

    ``at`` is the ISO-8601 timestamp stamped onto discovery-log entries; the
    caller supplies it so the log stays deterministic (discovery_log never reads
    the clock). Required whenever ``log_path`` is set.

    ``reviewer_tools`` is the tool allowlist config (issue #79 /
    docs/PANEL_VERDICT_SPEC.md §1.3), e.g. ``{"reviewers": {"tools": []}}`` —
    empty/absent means fully isolated (the default). Resolved per reviewer via
    :mod:`zenodotus.isolation` and enforced as the ONLY tools passed to
    ``provider.review``; anything the provider requests outside that allowlist
    is denied and surfaced in ``PanelReview.isolation``, never swallowed. Each
    ``DeniedAttempt.at`` is stamped from ``at`` when given; if ``at`` is
    omitted (no ``log_path``), it falls back to a real ISO-8601 UTC timestamp
    generated at call time — never an empty string — so a library caller's
    isolation record always satisfies ``docs/PANEL_VERDICT_SPEC.md`` §1.3.
    """
    if provider is not None and model is not None:
        raise ValueError(
            "Pass either `model=` or a pre-constructed `provider=`, not both: a "
            "caller-supplied provider owns its own model, and the Provider "
            "protocol has no model concept, so `model=` cannot be applied to it. "
            "To run a specific model on the default provider, pass `model=` "
            "without `provider=`; to control the model on a custom provider, "
            "configure it on that provider before passing it."
        )
    if provider is None:
        # Model precedence (issue #86), highest first: explicit `model=` kwarg >
        # ZENODOTUS_MODEL env var > DEFAULT_MODEL literal. (Rung 2 — a passed
        # provider's own model — is handled above: when a provider is supplied
        # we never reach here, so its configured model stands unmodified.) The
        # env var is read live so a caller (or test) that sets it after import
        # is honoured, rather than only its import-time snapshot in DEFAULT_MODEL.
        effective_model = (
            model
            if model is not None
            else os.environ.get("ZENODOTUS_MODEL") or DEFAULT_MODEL
        )
        provider = AnthropicProvider(model=effective_model)
    if consensus is None:
        consensus = any_blocker_no_go
    if log_path is not None and at is None:
        raise ValueError(
            "`at` (ISO-8601 timestamp) is required when writing a discovery log"
        )
    repo = repo_name or Path(path).name

    context = gather_context(path)

    verdicts: list[ReviewerVerdict] = []
    all_denied: list[isolation.DeniedAttempt] = []
    all_granted: set[str] = set()
    # Falsy check (not `is None`): an explicit `at=""` must fall back the same
    # as an omitted `at` — the §1.3 guarantee is "never empty", not "never
    # omitted" (Quine review, PR #81).
    effective_at = at if at else _iso_now()

    for i in range(n_reviewers):
        reviewer_id = f"reviewer-{i + 1}"
        policy = isolation.resolve_policy(reviewer_tools, reviewer_id)
        requested = list(getattr(provider, "requested_tools", []) or [])
        permitted = policy.filter_tools(requested, at=effective_at)
        granted_names = sorted(
            str(t.get("name", "")) for t in permitted if t.get("name")
        )
        all_denied.extend(policy.denied)
        # Accumulate, don't overwrite: the allowlist is panel-wide (issue #82,
        # docs/PANEL_VERDICT_SPEC.md §1.3), so what varies between reviewers is
        # not their *permitted* set but what the provider actually *requested*
        # on each call. This is the sole writer of isolation["tools"] — deleting
        # it turns PR #81's mutation test RED. Keep it.
        all_granted.update(granted_names)

        raw = provider.review(reviewer_id, context, tools=permitted)
        verdicts.append(
            ReviewerVerdict(
                reviewer=reviewer_id,
                go=bool(raw.get("go", False)),
                findings=list(raw.get("findings", [])),
                rationale=str(raw.get("rationale", "")),
                tools=granted_names,
            )
        )

    isolation_record = {
        "tools": sorted(all_granted),
        "denied": [d.as_dict() for d in all_denied],
    }

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
        isolation=isolation_record,
    )
