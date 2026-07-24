"""Shared "files that would actually ship" enumeration.

Both the leak self-check (``leakcheck.py``) and the no-context reviewer panel
(``panel.py``) must reason about what a repo would *actually publish* — respecting
``.gitignore`` — rather than the raw working tree. Untracked, generated artifacts
(``.venv/``, ``dist/``, ``.agents/``, ``.tmp/`` …) never ship, so scanning or
reviewing them only produces false positives on the developer's own laptop.

Inside a git work tree the authoritative answer is ``git ls-files``; outside one
(e.g. an extracted package artifact reviewed as a plain directory) we fall back to
a filtered ``rglob`` walk that mirrors common ``.gitignore`` entries by name.

Extracted here so the two callers cannot drift into two subtly different notions
of "shipped content" (issue #68).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Directories/files never part of a shipped artifact. Used ONLY for the non-git
# fallback walk; inside a git repo ``git ls-files`` is authoritative and this list
# is not consulted.
_UNTRACKED_DIRS = frozenset({
    ".git", ".venv", "venv", "env", ".env", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", ".tox", "node_modules", "dist", "build",
    ".eggs", ".agents", ".codex", ".tmp", "tmp", "coverage", "htmlcov",
    ".idea", ".vscode", ".DS_Store",
})
_UNTRACKED_FILES = frozenset({".DS_Store"})


def _which(tool: str) -> str | None:  # injectable seam, mirrors gates.py
    return shutil.which(tool)


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def tracked_files(root: Path) -> list[str] | None:
    """Git-tracked files under ``root`` (relative posix paths), or ``None`` if not git.

    Reflects what would actually ship — respecting ``.gitignore`` — instead of the
    raw working tree, so untracked/generated artifacts (``.venv/``, ``dist/``,
    ``.DS_Store``, ``.agents/``, ``.tmp/``) never present as shipped content.
    Returns ``None`` when git is unavailable or ``root`` is not a git work tree, so
    callers can fall back to :func:`walk_files`.
    """
    if _which("git") is None:
        return None
    inside = _run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    proc = _run(["git", "-C", str(root), "ls-files", "-z"])
    if proc.returncode != 0:
        return None
    return [f for f in proc.stdout.split("\0") if f]


def walk_files(root: Path) -> list[str]:
    """Fallback tree for a non-git target (e.g. an extracted package artifact).

    Filters obvious untracked/generated noise by name so a stray ``dist/`` or
    ``.venv/`` in a plain directory still doesn't read as shipped content.
    """
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if set(rel.parts) & _UNTRACKED_DIRS:
            continue
        if rel.name in _UNTRACKED_FILES:
            continue
        out.append(rel.as_posix())
    return out


def shippable_files(root: str | Path) -> list[str]:
    """Relative posix paths of the files that would actually ship from ``root``.

    Prefers ``git ls-files`` (authoritative, respects ``.gitignore``); falls back
    to a filtered walk outside a git work tree. This is the single enumeration both
    ``leakcheck.py`` and ``panel.py`` build on, so they cannot drift.
    """
    root = Path(root)
    tracked = tracked_files(root)
    return tracked if tracked is not None else walk_files(root)
