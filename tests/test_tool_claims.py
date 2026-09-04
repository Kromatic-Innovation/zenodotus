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
        text = path.read_text()
        tools.update(_WHICH_RE.findall(text))
        tools.update(_RUN_RE.findall(text))
    return tools


# --- claim extraction -------------------------------------------------------- #

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_DOUBLE_BACKTICK_RE = re.compile(r"``([^`]+?)``")
_SINGLE_BACKTICK_RE = re.compile(r"`([^`]+?)`")

# Invocation/membership verbs that turn a sentence into a "claim". "part of
# the ... gate" is handled separately since it's a phrase, not a single verb.
_VERB_RE = re.compile(
    r"\b(runs|is run|run by|invokes|is invoked|shells out to|calls|executes|"
    r"wired into)\b"
)
_GATE_PHRASE_RE = re.compile(r"\bpart of the\b[^.?!]*\bgate\b")

# "does not", "is deliberately not", etc. all contain "not"; "no longer" does
# not, so it's listed separately.
_NEGATION_RE = re.compile(r"\b(not|never|no longer)\b")

_TOKEN_REJECT_CHARS = set('/._()[]=$"\'')
# User-run installers / shell builtins — never the thing a *gate* invokes.
_INSTALLER_DENYLIST = {
    "pip", "pip3", "python", "python3", "pipx", "brew", "apt", "apt-get",
    "export", "cd", "make", "npx", "curl", "wget", "sh", "bash", "uv", "poetry",
}


@dataclass(frozen=True)
class ToolClaimViolation:
    tool: str
    sentence: str


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


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
    if any(ch in _TOKEN_REJECT_CHARS for ch in token):
        return None
    if any(ch.isupper() for ch in token):
        return None
    if token.lower() in _INSTALLER_DENYLIST:
        return None
    return token


def unbacked_tool_claims(text: str, call_site_tools: set[str]) -> list[ToolClaimViolation]:
    """Sentences that claim a tool RUNS with no backing call site.

    A sentence is a *claim* when it contains an invocation/membership verb
    AND at least one backticked span. A claim is a *violation* when a
    backtick span's candidate tool (its first whitespace token) is absent
    from ``call_site_tools`` — unless the sentence is negated (``not``,
    ``never``, ``no longer``, ...), in which case it is not a claim at all.
    """
    violations: list[ToolClaimViolation] = []
    for paragraph in _paragraphs(_strip_fences(text)):
        for sentence in _sentences(paragraph):
            if _NEGATION_RE.search(sentence):
                continue
            if not (_VERB_RE.search(sentence) or _GATE_PHRASE_RE.search(sentence)):
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


def repo_wide_violations(repo_root: Path = REPO_ROOT) -> list[tuple[Path, ToolClaimViolation]]:
    tools = call_site_tools(repo_root / "src" / "zenodotus")
    files = _tracked_markdown_files(repo_root) + sorted(
        (repo_root / "src" / "zenodotus").glob("*.py")
    )
    violations: list[tuple[Path, ToolClaimViolation]] = []
    for f in files:
        text = f.read_text()
        for v in unbacked_tool_claims(text, tools):
            violations.append((f, v))
    return violations


# --- tests --------------------------------------------------------------------- #

def test_repo_wide_scan_has_no_violations():
    violations = repo_wide_violations()
    assert violations == [], "\n".join(
        f"{f}: unbacked claim about `{v.tool}` — {v.sentence!r}" for f, v in violations
    )


def test_negative_fixture_flags_tool_with_no_call_site():
    text = (FIXTURES_DIR / "negative.md").read_text()
    result = unbacked_tool_claims(text, call_site_tools())
    assert any(v.tool == "flimflam" for v in result), result


def test_positive_fixture_backed_tools_produce_no_violation():
    text = (FIXTURES_DIR / "positive.md").read_text()
    result = unbacked_tool_claims(text, call_site_tools())
    assert result == [], result


def test_negation_fixture_produces_no_violation():
    text = (FIXTURES_DIR / "negation.md").read_text()
    result = unbacked_tool_claims(text, call_site_tools())
    assert result == [], result
