"""CI leak self-check — scan a repo for org-internal content before a public flip.

Belt-and-suspenders on the "no sensitive information" requirement (repo issue
#11, gating the public-flip issue #6): greps every text file for a configurable
denylist of internal markers and fails (non-zero exit) if any are present.

The built-in denylist targets *accidental* leaks that must never ship publicly —
local dev-machine paths and internal network hostnames. Organization-specific
markers (employee names, private repo slugs, internal Slack workspaces) are
added per-repo via a denylist file (default ``.zenodotus-leakcheck.txt``: one
regex per line, ``#`` comments) so this scanner needs no code change to tighten.

Deliberately NOT in the default denylist: the org name in the LICENSE copyright
and the ``hestia.yml`` fleet config are legitimate — flagging them would be a
false positive. Add narrower, higher-signal markers via the denylist file.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import fileset

# (regex, human label). Kept high-signal to avoid false positives on public repos.
DEFAULT_DENYLIST: list[tuple[str, str]] = [
    (r"~/Code(?:/|\b)", "home-dir dev path (~/Code)"),
    (r"/Users/[^/\s]+/(?:Code|Projects|src|dev)\b", "macOS dev path"),
    (r"/home/[^/\s]+/(?:Code|Projects|dev)\b", "linux dev path"),
    (r"\b[a-z0-9][a-z0-9.-]*\.(?:internal|corp|intranet|lan)\b", "internal hostname"),
]

# Default denylist-config filename (per-repo, regex per line).
DEFAULT_DENYLIST_FILE = ".zenodotus-leakcheck.txt"

# The ONE narrowing applied on top of the shared enumeration: files that
# legitimately CONTAIN the marker patterns as literals and would otherwise
# self-flag — this scanner's own source, the leakcheck test file (which plants
# sample leaks), and the denylist config. Deliberately NOT a directory filter:
# generated-artifact directories are fileset's business (its _UNTRACKED_DIRS is
# the single definition, consulted on the non-git fallback walk), and inside a
# git work tree a *tracked* dist/ or build/ file is shipped content that must be
# scanned like any other (issue #106).
_IGNORE_GLOBS = (
    "*.egg-info/*",
    "src/zenodotus/leakcheck.py",
    "tests/test_leakcheck.py",
    DEFAULT_DENYLIST_FILE,
)
_MAX_FILE_BYTES = 2_000_000


@dataclass
class LeakHit:
    file: str
    line: int
    label: str
    pattern: str
    text: str


def load_denylist_file(path: str | Path) -> list[tuple[str, str]]:
    """Parse a denylist file (one regex per line, ``#`` comments)."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[tuple[str, str]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append((line, f"denylist:{p.name}"))
    return out


def _iter_text_files(root: Path):
    # Enumerate only files that would actually ship (git-tracked, respecting
    # .gitignore) via the shared helper, so gitignored/generated local artifacts
    # (.agents/, .codex/, .tmp/, …) are never scanned and can't raise false
    # "leak" hits (issue #68). Outside a git work tree this falls back to a
    # filtered walk. panel.py consumes the same enumeration, and the only thing
    # dropped here is _IGNORE_GLOBS (self-exemption, see above) — so the two
    # callers reason about the same shipped file set (issue #106).
    for rel_posix in sorted(fileset.shippable_files(root)):
        rel = Path(rel_posix)
        if any(fnmatch.fnmatch(rel_posix, g) for g in _IGNORE_GLOBS):
            continue
        entry = root / rel
        try:
            if not entry.is_file():  # git may list a staged-then-deleted path
                continue
            if entry.stat().st_size > _MAX_FILE_BYTES:
                continue
            data = entry.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:  # skip binary
            continue
        yield rel_posix, data.decode("utf-8", errors="replace")


def scan(
    root: str | Path,
    *,
    patterns: list[tuple[str, str]] | None = None,
    denylist_file: str | Path | None = DEFAULT_DENYLIST_FILE,
) -> list[LeakHit]:
    """Scan ``root`` for internal markers; return every hit (empty list = clean)."""
    root = Path(root)
    rules = list(DEFAULT_DENYLIST)
    if denylist_file is not None:
        rules += load_denylist_file(root / denylist_file)
    if patterns:
        rules += patterns
    compiled = [(re.compile(rx), rx, label) for rx, label in rules]

    hits: list[LeakHit] = []
    for rel_posix, text in _iter_text_files(root):
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rx, raw, label in compiled:
                if rx.search(line):
                    hits.append(LeakHit(rel_posix, lineno, label, raw, line.strip()[:200]))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zenodotus-leakcheck",
        description="Scan a repo for internal markers before a public flip.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Repo path to scan (default: .)")
    parser.add_argument("--denylist-file", default=DEFAULT_DENYLIST_FILE,
                        help=f"Per-repo regex denylist (default: {DEFAULT_DENYLIST_FILE})")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit machine-readable results")
    args = parser.parse_args(argv)

    hits = scan(args.path, denylist_file=args.denylist_file)

    if args.as_json:
        print(json.dumps(
            {"clean": not hits, "hits": [h.__dict__ for h in hits]},
            indent=2, sort_keys=True,
        ))
    else:
        if not hits:
            print(f"leak-check: clean — no internal markers found in {args.path}")
        else:
            print(f"leak-check: FAILED — {len(hits)} internal marker(s) found:", file=sys.stderr)
            for h in hits:
                print(f"  {h.file}:{h.line}  [{h.label}]  {h.text}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
