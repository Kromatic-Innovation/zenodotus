"""Durable, machine-readable cross-repo verdict marker (issue #54).

When zenodotus reviews an EXTERNAL repo (``zenodotus review <path-or-repo>``), the
verdict needs to be recorded somewhere a separate tool — hestia's ``oss-status``
command — can read to answer "has zenodotus already cleared this repo's current
``main`` for publish?". Per the approved design (issue #54, occam / TriKro-approved
2026-07-21), the recording format reuses primitives that already exist: a GitHub
issue/PR comment on the target repo carrying a small structured HTML-comment
marker, mirroring the ``<!-- decision: ... -->`` convention already used across
the org. No new state file, service, or database.

This module owns exactly that marker: it RENDERS the marker zenodotus emits (the
"marker-writing step in zenodotus's own review routine" the design names as the
only new build), and it PARSES one back (a reference reader that keeps the format
honest and lets a consumer detect staleness). Actually posting the marker as a
GitHub comment is the caller's job (a human, or hestia's ``oss-status``) — keeping
zenodotus dependency-free and generic, consistent with
``docs/CROSS_REPO_VERDICT.md`` and the tool's local-invocation rule.

Staleness (design Q5) is free from the marker's ``sha`` field: a consumer compares
it to the target repo's current ``main`` HEAD — match ⇒ current, mismatch (or the
sentinel ``unknown`` when the reviewed tree was not a git checkout) ⇒ stale, never
silently shown as cleared.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from . import __version__

# Marker schema version. Bump when a field is renamed/removed (see design §2).
MARKER_VERSION = "v1"

# The verdict vocabulary recorded in the marker — zenodotus's three-state model
# (docs/PANEL_VERDICT_SPEC.md §1; issues #31/#53). The design's example used the
# older pass/conditional/fail words; we record the current pass/warn/block.
MARKER_VERDICTS = ("pass", "warn", "block")

# Sentinel recorded when the reviewed tree is not a git checkout, so no commit can
# be pinned. A consumer treats it as always-stale (never a false "cleared").
UNKNOWN_SHA = "unknown"

_OPEN = f"<!-- zenodotus-verdict: {MARKER_VERSION}"
_CLOSE = "-->"
_FIELDS = ("repo", "sha", "verdict", "ran_at", "runner")


def runner_string() -> str:
    """``zenodotus vX.Y.Z`` — the installed package version, best-effort.

    Prefers the installed distribution metadata (accurate) and falls back to the
    module ``__version__`` when the package is not installed (e.g. running from a
    source tree without an editable install).
    """
    try:
        ver = _pkg_version("zenodotus")
    except PackageNotFoundError:  # pragma: no cover - only without an install
        ver = __version__
    return f"zenodotus v{ver}"


def _which(tool: str) -> str | None:  # injectable seam, mirrors gates.py
    return shutil.which(tool)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def head_sha(path: str | Path) -> str:
    """Full commit SHA of ``path``'s git HEAD, or ``UNKNOWN_SHA`` if not a checkout.

    Also returns ``UNKNOWN_SHA`` when git itself is unavailable on ``PATH``, so a
    git-less host degrades to the always-stale sentinel instead of raising.
    """
    if _which("git") is None:
        return UNKNOWN_SHA
    root = str(path)
    inside = _run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return UNKNOWN_SHA
    proc = _run(["git", "-C", root, "rev-parse", "HEAD"])
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else UNKNOWN_SHA


def detect_repo_slug(path: str | Path) -> str | None:
    """Best-effort ``owner/name`` from ``path``'s ``origin`` remote, else ``None``.

    Recognises the common GitHub URL shapes (``https://github.com/owner/name(.git)``
    and ``git@github.com:owner/name(.git)``). Returns ``None`` when it cannot be
    determined; the caller then falls back to the directory name or an explicit
    ``--repo`` override — as it also does when git itself is unavailable on
    ``PATH``.
    """
    if _which("git") is None:
        return None
    proc = _run(["git", "-C", str(path), "remote", "get-url", "origin"])
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def resolve_repo(path: str | Path, override: str | None = None) -> str:
    """Repo slug to record: explicit override ⇒ detected remote ⇒ directory name."""
    if override:
        return override
    return detect_repo_slug(path) or Path(path).name


def render_verdict_marker(
    *, repo: str, sha: str, verdict: str, ran_at: str, runner: str | None = None
) -> str:
    """Render the ``<!-- zenodotus-verdict: v1 ... -->`` marker (design §2).

    ``verdict`` must be one of :data:`MARKER_VERDICTS`. ``runner`` defaults to the
    running zenodotus version. The output is a single HTML comment block, safe to
    drop verbatim into a GitHub issue/PR comment on the target repo.
    """
    if verdict not in MARKER_VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r} (expected one of {MARKER_VERDICTS})")
    runner = runner or runner_string()
    fields = {
        "repo": repo,
        "sha": sha,
        "verdict": verdict,
        "ran_at": ran_at,
        "runner": runner,
    }
    lines = [_OPEN]
    lines += [f"     {k}: {fields[k]}" for k in _FIELDS]
    lines.append(_CLOSE)
    return "\n".join(lines)


def parse_verdict_marker(text: str) -> dict | None:
    """Parse the first zenodotus-verdict marker in ``text``; ``None`` if absent.

    Returns ``{"version", "repo", "sha", "verdict", "ran_at", "runner"}``. A
    marker missing any required field, or carrying a verdict outside
    :data:`MARKER_VERDICTS`, is treated as malformed and yields ``None`` — a
    consumer must never read a partial marker as a valid clearance.
    """
    start = text.find(_OPEN)
    if start == -1:
        return None
    end = text.find(_CLOSE, start)
    if end == -1:
        return None
    body = text[start + len(_OPEN):end]

    out: dict[str, str] = {"version": MARKER_VERSION}
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key in _FIELDS:
            out[key] = val.strip()

    if any(f not in out for f in _FIELDS):
        return None
    if out["verdict"] not in MARKER_VERDICTS:
        return None
    return out
