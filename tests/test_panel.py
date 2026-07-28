"""Tests for the no-context reviewer panel.

No live API calls: a StubProvider replaces the Anthropic backend, and `at` is
supplied explicitly so discovery-log writes stay deterministic.
"""

from __future__ import annotations

import pytest

from zenodotus import panel
from zenodotus.discovery_log import load
from zenodotus.gates import GateResult
from zenodotus.panel import PanelReview, ReviewerVerdict


class StubProvider:
    """Returns canned verdicts in sequence (one per reviewer)."""

    def __init__(self, verdicts, requested_tools=None):
        self._verdicts = verdicts
        self.calls = []
        self.tool_calls = []
        self.requested_tools = requested_tools or []

    def review(self, reviewer_id, context, *, tools=None):
        self.calls.append((reviewer_id, context))
        self.tool_calls.append(tools or [])
        # cycle if fewer canned verdicts than reviewers
        return self._verdicts[
            (
                len(self.calls) - 1
                if len(self.calls) <= len(self._verdicts)
                else (len(self.calls) - 1) % len(self._verdicts)
            )
        ]


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "README.md").write_text("# Thing\nA useful public thing.\n")
    (d / "CONTRIBUTING.md").write_text("# Contributing\n")
    (d / "src").mkdir()
    (d / "src" / "thing.py").write_text("x = 1\n")
    return d


_GO = {"go": True, "rationale": "looks fine", "findings": []}


def _finding(category="coherence", severity="major", finding="README assumes context"):
    return {
        "finding": finding,
        "category": category,
        "severity": severity,
        "rationale": "an outsider can't follow it",
    }


# --- reviewer rubric framing (#53) ------------------------------------------- #


def _norm(s: str) -> str:
    # collapse the rubric's hard line-wraps so substring checks aren't foiled by
    # where a phrase happens to wrap across lines.
    return " ".join(s.split()).lower()


def test_rubric_frames_review_as_pre_publish_candidate():
    # AC1 (#53): the persona prompt must explicitly frame the review as a
    # pre-publish candidate assessment, not a live-artifact audit.
    rubric = _norm(panel.REVIEWER_RUBRIC)
    assert "pre-publish release candidate" in rubric
    assert "not the live published artifact" in rubric
    assert "about to replace the current live version" in rubric


def test_rubric_says_registry_lag_is_not_a_blocker():
    # AC2 (#53): a finding whose only basis is "the live registry hasn't caught
    # up to this candidate yet" is a release-day note, never a blocker/no-go.
    rubric = _norm(panel.REVIEWER_RUBRIC)
    assert "release-day checklist note" in rubric
    assert "never a `blocker` and never a reviewer no-go" in rubric
    assert "resolve automatically on publish" in rubric


# --- basic shape ------------------------------------------------------------- #


def test_review_returns_per_reviewer_verdicts_and_consensus(repo):
    provider = StubProvider([_GO, _GO, _GO])
    result = panel.review(str(repo), n_reviewers=3, provider=provider)
    assert isinstance(result, PanelReview)
    assert len(result.verdicts) == 3
    assert all(isinstance(v, ReviewerVerdict) for v in result.verdicts)
    assert result.consensus_go is True
    assert len(provider.calls) == 3


def test_reviewers_are_independent_and_no_context(repo):
    # every reviewer gets the SAME gathered public context and a distinct id;
    # none is handed anything the others produced.
    provider = StubProvider([_GO])
    panel.review(str(repo), n_reviewers=3, provider=provider)
    ids = [c[0] for c in provider.calls]
    contexts = [c[1] for c in provider.calls]
    assert ids == ["reviewer-1", "reviewer-2", "reviewer-3"]
    assert len(set(contexts)) == 1  # identical context => blind to each other's output
    assert "README" in contexts[0]  # public files only


# --- consensus --------------------------------------------------------------- #


def test_blocker_forces_no_go(repo):
    verdict = {
        "go": False,
        "rationale": "leak",
        "findings": [_finding(severity="blocker")],
    }
    provider = StubProvider([_GO, verdict, _GO])
    result = panel.review(str(repo), n_reviewers=3, provider=provider)
    assert result.consensus_go is False


def test_any_reviewer_no_go_blocks(repo):
    verdict = {"go": False, "rationale": "no", "findings": []}
    provider = StubProvider([_GO, _GO, verdict])
    result = panel.review(str(repo), n_reviewers=3, provider=provider)
    assert result.consensus_go is False


def test_custom_consensus_callable(repo):
    provider = StubProvider([_GO])
    result = panel.review(
        str(repo), n_reviewers=2, provider=provider, consensus=lambda verdicts: False
    )
    assert result.consensus_go is False


# --- three-state verdict projection (docs/PANEL_VERDICT_SPEC.md §1.1) --------- #


def test_panel_verdict_pass_when_clean(repo):
    result = panel.review(str(repo), n_reviewers=3, provider=StubProvider([_GO]))
    assert panel.panel_verdict(result) == "pass"


def test_panel_verdict_warn_on_advisory_findings(repo):
    # go=True with only major/minor findings => warn (advisory), not block.
    verdict = {"go": True, "rationale": "nit", "findings": [_finding(severity="major")]}
    result = panel.review(str(repo), n_reviewers=3, provider=StubProvider([verdict]))
    assert result.consensus_go is True
    assert panel.panel_verdict(result) == "warn"


def test_panel_verdict_block_on_blocker(repo):
    verdict = {
        "go": False,
        "rationale": "no",
        "findings": [_finding(severity="blocker")],
    }
    result = panel.review(
        str(repo), n_reviewers=3, provider=StubProvider([_GO, verdict, _GO])
    )
    assert panel.panel_verdict(result) == "block"


def test_panel_verdict_block_on_bare_no_go(repo):
    # a reviewer no-go with no blocker finding still projects to block: per the
    # spec §1.1 a per-reviewer no-go is equivalent to a blocker for the aggregate.
    verdict = {"go": False, "rationale": "no", "findings": []}
    result = panel.review(
        str(repo), n_reviewers=3, provider=StubProvider([_GO, _GO, verdict])
    )
    assert panel.panel_verdict(result) == "block"


# --- discovery logging ------------------------------------------------------- #


def test_panel_only_findings_written_with_missed_by_deterministic(repo, tmp_path):
    verdict = {
        "go": False,
        "rationale": "x",
        "findings": [_finding(), _finding(category="naming")],
    }
    provider = StubProvider([verdict])
    log = tmp_path / "discoveries.jsonl"
    result = panel.review(
        str(repo),
        n_reviewers=2,
        provider=provider,
        log_path=log,
        at="2026-07-20T00:00:00Z",
        repo_name="ex/repo",
    )
    rows = load(log)
    assert len(rows) == 4  # 2 findings x 2 reviewers
    assert all(r["missed_by_deterministic"] is True for r in rows)
    assert all(r["caught_by"] == "panel" for r in rows)
    assert all(r["repo"] == "ex/repo" for r in rows)
    assert {r["category"] for r in rows} == {"coherence", "naming"}
    assert len(result.discoveries) == 4


def test_unknown_category_coerced_to_other(repo, tmp_path):
    verdict = {
        "go": False,
        "rationale": "x",
        "findings": [
            {"finding": "f", "category": "bogus", "severity": "minor", "rationale": "r"}
        ],
    }
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    panel.review(
        str(repo),
        n_reviewers=1,
        provider=provider,
        log_path=log,
        at="2026-07-20T00:00:00Z",
    )
    rows = load(log)
    assert rows[0]["category"] == "other"


def test_finding_caught_by_failing_deterministic_gate_is_not_logged(repo, tmp_path):
    # a leakage finding is deduped only when no_secrets actually FAILED
    verdict = {
        "go": False,
        "rationale": "x",
        "findings": [_finding(category="leakage"), _finding(category="coherence")],
    }
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    failed_secrets = GateResult("no_secrets", passed=False, detail="leak found")
    panel.review(
        str(repo),
        n_reviewers=1,
        provider=provider,
        gate_results=[failed_secrets],
        log_path=log,
        at="2026-07-20T00:00:00Z",
    )
    rows = load(log)
    # leakage deduped (already caught), coherence still logged
    assert [r["category"] for r in rows] == ["coherence"]


def test_passing_gate_does_not_dedupe(repo, tmp_path):
    verdict = {
        "go": False,
        "rationale": "x",
        "findings": [_finding(category="leakage")],
    }
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    passed_secrets = GateResult("no_secrets", passed=True, detail="clean")
    panel.review(
        str(repo),
        n_reviewers=1,
        provider=provider,
        gate_results=[passed_secrets],
        log_path=log,
        at="2026-07-20T00:00:00Z",
    )
    rows = load(log)
    assert len(rows) == 1  # floor passed => panel finding is a genuine discovery


def test_log_path_requires_at(repo, tmp_path):
    provider = StubProvider([_GO])
    with pytest.raises(ValueError):
        panel.review(
            str(repo), n_reviewers=1, provider=provider, log_path=tmp_path / "d.jsonl"
        )


def test_no_log_path_still_returns_discoveries(repo):
    verdict = {"go": False, "rationale": "x", "findings": [_finding()]}
    provider = StubProvider([verdict])
    result = panel.review(
        str(repo), n_reviewers=1, provider=provider, at="2026-07-20T00:00:00Z"
    )
    assert len(result.discoveries) == 1
    assert result.discoveries[0].missed_by_deterministic is True


# --- default provider is lazy ------------------------------------------------ #


def test_default_provider_does_not_need_sdk_at_import():
    # constructing the provider must not import anthropic or need a key
    p = panel.AnthropicProvider()
    assert p.model  # e.g. "claude-opus-4-8"
    assert p._client is None


def test_gather_context_includes_public_files_only(repo):
    ctx = panel.gather_context(str(repo))
    assert "README" in ctx
    assert "File tree" in ctx
    assert "thing.py" in ctx  # appears in the tree


# --- gather_context precision (issue #30 regression) ------------------------- #
# The no-context panel raised false blockers traced entirely to three gather
# defects (tickle-stick / athenaeum prove-itself runs): truncated-but-complete
# READMEs read as "unfinished", untracked working-tree noise read as "leaked
# internal files", and an omitted LICENSE body read as "license uncertainty".

import shutil
import subprocess


def test_gather_context_includes_license_body(tmp_path):
    # defect 3: the LICENSE body is present so reviewers can resolve license
    # questions instead of raising license-mismatch/uncertainty findings.
    d = tmp_path / "rc"
    d.mkdir()
    (d / "README.md").write_text("# Thing\n")
    (d / "LICENSE").write_text(
        "Apache License\nVersion 2.0\n\nGrant of Copyright License...\n"
    )
    ctx = panel.gather_context(str(d))
    assert "## LICENSE" in ctx
    assert "Grant of Copyright License" in ctx


def test_gather_context_does_not_truncate_long_but_complete_readme(tmp_path):
    # defect 1: a long-but-complete README (tickle-stick was 13,901 chars, well
    # past the old 8,000 cap) must appear in full, with no truncation annotation.
    d = tmp_path / "rc"
    d.mkdir()
    body = "# Big project\n\n" + ("An honest, complete sentence about the tool. " * 400)
    assert len(body) > 8000  # would have been sliced under the old cap
    (d / "README.md").write_text(body)
    ctx = panel.gather_context(str(d))
    assert body in ctx  # whole file, not cut at 8,000 mid-word
    assert "omitted" not in ctx  # no truncation annotation for an in-cap file


def test_gather_context_annotates_when_file_exceeds_cap(tmp_path, monkeypatch):
    # defect 1: if the cap is ever hit, the omission is annotated as COMPLETE-
    # upstream rather than silently cut, so it never reads as "unfinished".
    d = tmp_path / "rc"
    d.mkdir()
    monkeypatch.setattr(panel, "_MAX_FILE_CHARS", 50)
    (d / "README.md").write_text("A" * 500)
    ctx = panel.gather_context(str(d))
    assert "450 more character" in ctx  # 500 - 50 omitted
    assert "COMPLETE, not" in ctx  # explicit "not truncated/unfinished" annotation


def test_gather_context_uses_tracked_files_only_in_git_repo(tmp_path):
    # defect 2: inside a git work tree, only tracked files appear — untracked
    # generated noise (.venv/, dist/, .DS_Store) must not present as shipped.
    if shutil.which("git") is None:  # pragma: no cover - git is a CI dependency
        import pytest as _pytest

        _pytest.skip("git not available")
    d = tmp_path / "rc"
    d.mkdir()
    (d / "README.md").write_text("# Real\nShipped content.\n")
    (d / "src").mkdir()
    (d / "src" / "core.py").write_text("value = 1\n")
    (d / ".venv").mkdir()
    (d / ".venv" / "junk.py").write_text("internal_only = 1\n")
    (d / "dist").mkdir()
    (d / "dist" / "pkg.whl").write_text("built artifact\n")
    (d / ".DS_Store").write_text("mac noise\n")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "add", "README.md", "src/core.py"], cwd=d, check=True)
    ctx = panel.gather_context(str(d))
    assert "src/core.py" in ctx  # tracked file present in the tree
    assert ".venv" not in ctx
    assert "dist/pkg.whl" not in ctx
    assert ".DS_Store" not in ctx


def test_gather_context_fallback_filters_junk_without_git(tmp_path):
    # defect 2 fallback: for a non-git target (e.g. an extracted package), the
    # walk still drops obvious untracked/generated noise by name.
    d = tmp_path / "pkg"  # a plain directory, deliberately NOT git-initialised
    d.mkdir()
    (d / "README.md").write_text("# Pkg\n")
    (d / "node_modules").mkdir()
    (d / "node_modules" / "dep.js").write_text("module.exports = 1\n")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "x.pyc").write_text("bytecode\n")
    ctx = panel.gather_context(str(d))
    assert "README.md" in ctx
    assert "node_modules" not in ctx
    assert "__pycache__" not in ctx


# --- reviewer tool isolation (issue #79 / docs/PANEL_VERDICT_SPEC.md §1.3) --- #


def test_default_config_denies_all_tools(repo):
    # a provider that wants a tool gets nothing when reviewer_tools is unset.
    provider = StubProvider([_GO], requested_tools=[{"name": "recall"}])
    result = panel.review(
        str(repo), n_reviewers=1, provider=provider, at="2026-07-20T00:00:00Z"
    )
    assert result.verdicts[0].tools == []
    assert result.isolation == {
        "tools": [],
        "denied": [
            {"tool": "recall", "reviewer": "reviewer-1", "at": "2026-07-20T00:00:00Z"}
        ],
    }
    # the provider itself must never see the denied declaration either.
    assert provider.tool_calls == [[]]


def test_explicit_allowlist_permits_named_tool(repo):
    provider = StubProvider([_GO], requested_tools=[{"name": "recall"}])
    result = panel.review(
        str(repo),
        n_reviewers=1,
        provider=provider,
        at="2026-07-20T00:00:00Z",
        reviewer_tools={"reviewers": {"tools": ["recall"]}},
    )
    assert result.verdicts[0].tools == ["recall"]
    assert result.isolation == {"tools": ["recall"], "denied": []}
    assert provider.tool_calls == [[{"name": "recall"}]]


def test_discovery_capability_not_implicitly_granted(repo):
    # allowing one tool must not implicitly admit a tool-search/discovery
    # capability — it has to be named on the allowlist itself, same as any
    # other tool. No blocklist of "discovery-sounding" names is involved; this
    # is the same exact-name-match path every other tool goes through.
    provider = StubProvider(
        [_GO], requested_tools=[{"name": "recall"}, {"name": "ToolSearch"}]
    )
    result = panel.review(
        str(repo),
        n_reviewers=1,
        provider=provider,
        at="2026-07-20T00:00:00Z",
        reviewer_tools={"reviewers": {"tools": ["recall"]}},
    )
    assert result.verdicts[0].tools == ["recall"]
    assert result.isolation["tools"] == ["recall"]
    assert result.isolation["denied"] == [
        {"tool": "ToolSearch", "reviewer": "reviewer-1", "at": "2026-07-20T00:00:00Z"}
    ]


def test_denied_attempt_surfaced_per_reviewer_not_swallowed(repo):
    provider = StubProvider([_GO, _GO], requested_tools=[{"name": "WebSearch"}])
    result = panel.review(
        str(repo), n_reviewers=2, provider=provider, at="2026-07-20T00:00:00Z"
    )
    assert len(result.isolation["denied"]) == 2
    assert {d["reviewer"] for d in result.isolation["denied"]} == {
        "reviewer-1",
        "reviewer-2",
    }


def test_isolation_tools_is_union_across_reviewers():
    # zenodotus's per-panel allowlist is uniform today, but the union rule
    # (spec §1.3) must still hold: the aggregate is every reviewer's granted set.
    from zenodotus import isolation

    p1 = isolation.ToolPolicy(reviewer="reviewer-1", allowed=frozenset({"recall"}))
    p2 = isolation.ToolPolicy(reviewer="reviewer-2", allowed=frozenset({"WebSearch"}))
    granted = set()
    for p, requested in ((p1, [{"name": "recall"}]), (p2, [{"name": "WebSearch"}])):
        permitted = p.filter_tools(requested, at="2026-07-20T00:00:00Z")
        granted.update(t["name"] for t in permitted)
    assert granted == {"recall", "WebSearch"}


def test_anthropic_provider_defaults_to_no_requested_tools():
    p = panel.AnthropicProvider()
    assert p.requested_tools == []
