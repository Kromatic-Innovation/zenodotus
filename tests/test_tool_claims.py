"""Guard: no doc/docstring may claim an external tool RUNS unless a real
subprocess call site backs the claim.

Call sites are derived from ``src/zenodotus/*.py`` itself (``_which("X")`` /
``_run(["X", ...])`` string literals) — never from a hardcoded list, so this
test cannot go stale the way the docs it guards did (zenodotus#115).

Extraction is a DENYLIST, not an allowlist of known tools: a sentence naming
a brand-new, never-before-seen tool is flagged exactly like one naming
``twine``. See ``unbacked_tool_claims`` for the algorithm.

Fixtures that deliberately contain violations live under
tests/fixtures/tool_claims/ and are excluded from the repo-wide scan (the
scan only covers tracked *.md files and src/zenodotus/*.py, both outside
tests/).

Two additional, mechanically-derived exemptions apply ONLY to the repo-wide
scan (never to the fixture tests, which exercise the raw algorithm): a
candidate that names a path component of any tracked file, and a candidate
that names a job key in .github/workflows/*.yml. Both are stated precision
trade-offs, not a tool allowlist — see ``known_candidates`` for exactly what
they cover and what they'd miss.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "zenodotus"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "tool_claims"

# --- deriving the backed tool set from code --------------------------------- #

_WHICH_RE = re.compile(r'_which\(\s*"([a-zA-Z0-9_-]+)"\s*\)')
_RUN_RE = re.compile(r'_run\(\s*\[\s*"([a-zA-Z0-9_-]+)"')


def call_site_tools(src_dir: Path = SRC_DIR) -> set[str]:
    """Tools with a real subprocess call site under src/zenodotus/*.py."""
    tools: set[str] = set()
    for path in sorted(src_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tools.update(_WHICH_RE.findall(text))
        tools.update(_RUN_RE.findall(text))
    return tools


# --- claim extraction -------------------------------------------------------- #

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_DOUBLE_BACKTICK_RE = re.compile(r"``([^`]+?)``")
_SINGLE_BACKTICK_RE = re.compile(r"`([^`]+?)`")
_TABLE_ROW_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_LINE_RE = re.compile(r"^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")

# Invocation/membership verbs that turn a sentence into a "claim". "part of
# the ... gate" is handled separately since it's a phrase, not a single verb.
# NOTE: "calls" was deliberately dropped — it's the one homograph in this
# list (compare "gates.py calls gitleaks" (verb) vs. "no live LLM calls
# happen in tests" (plain noun)), and every genuine invocation claim in this
# domain is already covered by one of the unambiguous verbs below.
_VERB_RE = re.compile(
    r"\b(runs|is run|run by|invokes|is invoked|shells out to|executes|"
    r"wired into)\b"
)
_GATE_PHRASE_RE = re.compile(r"\bpart of the\b[^.?!]*\bgate\b")

# "does not", "is deliberately not", etc. all contain "not"; "no longer" does
# not, so it's listed separately.
_NEGATION_RE = re.compile(r"\b(not|never|no longer)\b")
# Markdown emphasis markers, stripped before verb/negation matching only, so
# "is deliberately **not** run by" still reads as negated (candidate/backtick
# extraction below runs on the ORIGINAL sentence and is unaffected).
_EMPHASIS_RE = re.compile(r"[*_]")
# How far back (chars) from a verb occurrence to look for a negation token.
# Roughly 3-5 words — enough for "is deliberately **not** run by" but not so
# much that unrelated negation elsewhere in a long sentence gets credited.
_NEGATION_LOOKBACK_CHARS = 30

_TOKEN_REJECT_CHARS = set('/._()[]=$"\'')
# User-run installers / shell builtins — never the thing a *gate* invokes.
_INSTALLER_DENYLIST = {
    "pip", "pip3", "python", "python3", "pipx", "brew", "apt", "apt-get",
    "export", "cd", "make", "npx", "curl", "wget", "sh", "bash", "uv", "poetry",
}
# Zenodotus's own three-state verdict/gate-status vocabulary (panel.py's
# `PASS, WARN, BLOCK = "pass", "warn", "block"`, verdict_marker.py's
# MARKER_VERDICTS, and GateResult's `skipped` status) — these get the same
# backtick-as-literal styling as tool names throughout the docs, but they are
# definitionally not tools. Same category as the installer denylist above:
# a small, closed, principled set, not an allowlist of *tools*.
_STATUS_DENYLIST = {"pass", "warn", "block", "skipped"}
_MIN_CANDIDATE_LEN = 3


@dataclass(frozen=True)
class ToolClaimViolation:
    tool: str
    sentence: str


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _flatten_tables(text: str) -> str:
    """Split markdown pipe tables into one paragraph per CELL.

    A table is structured data, not prose: reading a whole row as a single
    sentence ties a verb in one cell to a backtick span in an unrelated one
    (a `no_secrets` cell next to an install command, read as one run-on
    claim). But dropping tables outright would leave the README extras table
    -- the exact site this guard exists to protect -- silently unscanned, so
    each cell is emitted as its own paragraph and scanned normally instead.

    Detected structurally (a row line immediately followed by a separator
    line), not by file/line. Stated trade-off: a cell containing an escaped
    pipe splits mid-cell, which can separate a verb from its tool; that
    direction is a missed claim, not a false alarm.
    """
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if (_TABLE_ROW_LINE_RE.match(lines[i]) and i + 1 < n
                and _TABLE_SEPARATOR_LINE_RE.match(lines[i + 1])):
            rows = [lines[i]]
            i += 2  # header row consumed above; skip the `---` separator
            while i < n and _TABLE_ROW_LINE_RE.match(lines[i]):
                rows.append(lines[i])
                i += 1
            for row in rows:
                for cell in row.strip().strip("|").split("|"):
                    cell = cell.strip()
                    if cell:
                        out.extend([cell, ""])
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _paragraphs(text: str) -> list[str]:
    out = []
    for raw in re.split(r"\n\s*\n", text):
        norm = re.sub(r"\s+", " ", raw).strip()
        if norm:
            out.append(norm)
    return out


def _sentences(paragraph: str) -> list[str]:
    # Semicolons join independent clauses the same way periods separate
    # sentences, and treating them as boundaries avoids tying a verb in one
    # clause to an unrelated backtick span in the next.
    parts = re.split(r"(?<=[.!?;])\s+", paragraph)
    return [p.strip() for p in parts if p.strip()]


def _backtick_spans(sentence: str) -> list[str]:
    """Backtick-span contents, handling both `single` and ``double`` (RST)."""
    spans: list[str] = []

    def _take(m: re.Match[str]) -> str:
        spans.append(m.group(1))
        return " "

    remainder = _DOUBLE_BACKTICK_RE.sub(_take, sentence)
    _SINGLE_BACKTICK_RE.sub(_take, remainder)
    return spans


def _candidate_tool(span: str) -> str | None:
    token = span.strip().split()[0] if span.strip() else ""
    if not token:
        return None
    if token.startswith("-"):
        return None  # a CLI flag (`--shadow`, `--include-optional`), not a tool
    if len(token) < _MIN_CANDIDATE_LEN:
        return None  # every real call-site tool is >=3 chars (git, npm, pyroma,
        # gitleaks, licensee, scorecard); a 1-2 char span is a parameter/attribute
        # name (e.g. `at`), not a tool. Precision trade-off, stated: a future
        # tool with a 1-2 char name would slip through this exemption too.
    if any(ch in _TOKEN_REJECT_CHARS for ch in token):
        return None
    if any(ch.isupper() for ch in token):
        return None
    if token.lower() in _INSTALLER_DENYLIST or token.lower() in _STATUS_DENYLIST:
        return None
    return token


def _verb_occurrences(text: str) -> list[tuple[int, int]]:
    """Start/end offsets of every invocation-verb or gate-phrase match."""
    spans = [m.span() for m in _VERB_RE.finditer(text)]
    spans += [m.span() for m in _GATE_PHRASE_RE.finditer(text)]
    return spans


def _is_negated_occurrence(text: str, start: int) -> bool:
    window = text[max(0, start - _NEGATION_LOOKBACK_CHARS):start]
    return bool(_NEGATION_RE.search(window))


def _sentence_is_claim(sentence: str) -> bool:
    """A sentence is a claim unless EVERY verb/gate-phrase occurrence in it
    is negated by a nearby preceding negation token (see module docstring).

    Negation is checked per-occurrence, not sentence-wide: an unrelated
    "not" elsewhere in a long sentence must not exempt a real claim (this is
    what let "`twine check` runs ... when artifacts are not yet built."
    slip through an earlier, sentence-wide version of this check).
    """
    cleaned = _EMPHASIS_RE.sub("", sentence)
    occurrences = _verb_occurrences(cleaned)
    if not occurrences:
        return False
    return not all(_is_negated_occurrence(cleaned, start) for start, _ in occurrences)


def unbacked_tool_claims(text: str, call_site_tools: set[str]) -> list[ToolClaimViolation]:
    """Sentences that claim a tool RUNS with no backing call site.

    A sentence is a *claim* when it contains an invocation/membership verb
    AND at least one backticked span, and the verb occurrence is not
    negated (see ``_sentence_is_claim``). A claim is a *violation* when a
    backtick span's candidate tool (its first whitespace token) is absent
    from ``call_site_tools``.
    """
    violations: list[ToolClaimViolation] = []
    for paragraph in _paragraphs(_flatten_tables(_strip_fences(text))):
        for sentence in _sentences(paragraph):
            if not _sentence_is_claim(sentence):
                continue
            spans = _backtick_spans(sentence)
            for span in spans:
                candidate = _candidate_tool(span)
                if candidate is None:
                    continue
                if candidate not in call_site_tools:
                    violations.append(ToolClaimViolation(tool=candidate, sentence=sentence))
    return violations


# --- repo-wide scan ----------------------------------------------------------- #

def _tracked_markdown_files(repo_root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout
    files = [Path(line) for line in out.splitlines() if line]
    return [repo_root / f for f in files if f.parts[0] != "tests"]


def _tracked_path_components(repo_root: Path) -> set[str]:
    """Every directory name and extension-stripped filename git tracks.

    Precision trade-off: exempts a candidate that merely names a repo path
    component (covers the eval fixture dirs `mediocre-readme` /
    `clean-complete`, and the package dir `zenodotus`) — a future *tool*
    that happens to share a name with a repo directory or file would slip
    through this exemption too. Mechanically derived from `git ls-files`,
    never a hardcoded list.
    """
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout
    components: set[str] = set()
    for line in out.splitlines():
        if not line:
            continue
        p = Path(line)
        components.update(p.parts[:-1])
        components.add(p.stem)
    return components


def _workflow_job_keys(repo_root: Path) -> set[str]:
    """Top-level job keys under `jobs:` in every .github/workflows/*.yml.

    Precision trade-off: exempts a candidate that merely names a CI job
    (covers `leak-check` / `ci-required`) — a future *tool* sharing a name
    with a CI job would slip through this exemption too. Mechanically
    derived from the workflow files, never a hardcoded list.
    """
    keys: set[str] = set()
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return keys
    for path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        in_jobs = False
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            if re.match(r"^\S", line):  # dedent back to column 0 ends `jobs:`
                in_jobs = False
                continue
            m = re.match(r"^  ([a-zA-Z0-9_-]+):", line)
            if m:
                keys.add(m.group(1))
    return keys


def known_candidates(repo_root: Path = REPO_ROOT) -> set[str]:
    """Backed tools, plus the repo-wide-scan-only precision exemptions."""
    return (
        call_site_tools(repo_root / "src" / "zenodotus")
        | _tracked_path_components(repo_root)
        | _workflow_job_keys(repo_root)
    )


def repo_wide_violations(repo_root: Path = REPO_ROOT) -> list[tuple[Path, ToolClaimViolation]]:
    known = known_candidates(repo_root)
    files = _tracked_markdown_files(repo_root) + sorted(
        (repo_root / "src" / "zenodotus").glob("*.py")
    )
    violations: list[tuple[Path, ToolClaimViolation]] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for v in unbacked_tool_claims(text, known):
            violations.append((f, v))
    return violations


# --- tests --------------------------------------------------------------------- #

def test_repo_wide_scan_has_no_violations():
    violations = repo_wide_violations()
    assert violations == [], "\n".join(
        f"{f}: unbacked claim about `{v.tool}` — {v.sentence!r}" for f, v in violations
    )


def test_negative_fixture_flags_tool_with_no_call_site():
    text = (FIXTURES_DIR / "negative.md").read_text(encoding="utf-8")
    result = unbacked_tool_claims(text, call_site_tools())
    assert any(v.tool == "flimflam" for v in result), result


def test_positive_fixture_backed_tools_produce_no_violation():
    text = (FIXTURES_DIR / "positive.md").read_text(encoding="utf-8")
    result = unbacked_tool_claims(text, call_site_tools())
    assert result == [], result


def test_negation_fixture_produces_no_violation():
    text = (FIXTURES_DIR / "negation.md").read_text(encoding="utf-8")
    result = unbacked_tool_claims(text, call_site_tools())
    assert result == [], result


def test_unrelated_negation_elsewhere_in_sentence_still_flags():
    """A "not" far from the verb occurrence must not exempt a real claim —
    the bug that let a reintroduced "`twine check` runs ... when artifacts
    are not yet built." slip through a sentence-wide negation check."""
    text = (FIXTURES_DIR / "unrelated_negation.md").read_text(encoding="utf-8")
    result = unbacked_tool_claims(text, call_site_tools())
    assert any(v.tool == "flimflam" for v in result), result


def test_table_cell_claims_are_scanned():
    """A claim inside a markdown table cell must still be caught.

    Tables are flattened per CELL rather than dropped: the README extras
    table is the exact site this guard protects, so skipping tables
    wholesale would leave a silent hole there (zenodotus#115)."""
    text = (FIXTURES_DIR / "table.md").read_text(encoding="utf-8")
    result = unbacked_tool_claims(text, call_site_tools())
    assert [v.tool for v in result] == ["flimflam"], result
