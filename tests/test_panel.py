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

    def __init__(self, verdicts):
        self._verdicts = verdicts
        self.calls = []

    def review(self, reviewer_id, context):
        self.calls.append((reviewer_id, context))
        # cycle if fewer canned verdicts than reviewers
        return self._verdicts[len(self.calls) - 1 if len(self.calls) <= len(self._verdicts)
                               else (len(self.calls) - 1) % len(self._verdicts)]


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
    return {"finding": finding, "category": category, "severity": severity,
            "rationale": "an outsider can't follow it"}


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
    verdict = {"go": False, "rationale": "leak", "findings": [_finding(severity="blocker")]}
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
    result = panel.review(str(repo), n_reviewers=2, provider=provider,
                          consensus=lambda verdicts: False)
    assert result.consensus_go is False


# --- discovery logging ------------------------------------------------------- #

def test_panel_only_findings_written_with_missed_by_deterministic(repo, tmp_path):
    verdict = {"go": False, "rationale": "x", "findings": [_finding(), _finding(category="naming")]}
    provider = StubProvider([verdict])
    log = tmp_path / "discoveries.jsonl"
    result = panel.review(str(repo), n_reviewers=2, provider=provider,
                          log_path=log, at="2026-07-20T00:00:00Z", repo_name="ex/repo")
    rows = load(log)
    assert len(rows) == 4  # 2 findings x 2 reviewers
    assert all(r["missed_by_deterministic"] is True for r in rows)
    assert all(r["caught_by"] == "panel" for r in rows)
    assert all(r["repo"] == "ex/repo" for r in rows)
    assert {r["category"] for r in rows} == {"coherence", "naming"}
    assert len(result.discoveries) == 4


def test_unknown_category_coerced_to_other(repo, tmp_path):
    verdict = {"go": False, "rationale": "x",
               "findings": [{"finding": "f", "category": "bogus", "severity": "minor",
                             "rationale": "r"}]}
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    panel.review(str(repo), n_reviewers=1, provider=provider, log_path=log,
                 at="2026-07-20T00:00:00Z")
    rows = load(log)
    assert rows[0]["category"] == "other"


def test_finding_caught_by_failing_deterministic_gate_is_not_logged(repo, tmp_path):
    # a leakage finding is deduped only when no_secrets actually FAILED
    verdict = {"go": False, "rationale": "x",
               "findings": [_finding(category="leakage"), _finding(category="coherence")]}
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    failed_secrets = GateResult("no_secrets", passed=False, detail="leak found")
    panel.review(str(repo), n_reviewers=1, provider=provider, gate_results=[failed_secrets],
                 log_path=log, at="2026-07-20T00:00:00Z")
    rows = load(log)
    # leakage deduped (already caught), coherence still logged
    assert [r["category"] for r in rows] == ["coherence"]


def test_passing_gate_does_not_dedupe(repo, tmp_path):
    verdict = {"go": False, "rationale": "x", "findings": [_finding(category="leakage")]}
    provider = StubProvider([verdict])
    log = tmp_path / "d.jsonl"
    passed_secrets = GateResult("no_secrets", passed=True, detail="clean")
    panel.review(str(repo), n_reviewers=1, provider=provider, gate_results=[passed_secrets],
                 log_path=log, at="2026-07-20T00:00:00Z")
    rows = load(log)
    assert len(rows) == 1  # floor passed => panel finding is a genuine discovery


def test_log_path_requires_at(repo, tmp_path):
    provider = StubProvider([_GO])
    with pytest.raises(ValueError):
        panel.review(str(repo), n_reviewers=1, provider=provider, log_path=tmp_path / "d.jsonl")


def test_no_log_path_still_returns_discoveries(repo):
    verdict = {"go": False, "rationale": "x", "findings": [_finding()]}
    provider = StubProvider([verdict])
    result = panel.review(str(repo), n_reviewers=1, provider=provider, at="2026-07-20T00:00:00Z")
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
