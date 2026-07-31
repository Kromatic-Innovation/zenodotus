"""Tests for the record/replay cassette layer + the deterministic panel eval.

The eval runs the real panel over a committed fixture repo using a committed
cassette — fully offline, no live LLM calls — and asserts a reproducible verdict
and discovery set (issue #10; underpins the eval suite, #5).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zenodotus import panel
from zenodotus.cassette import CassetteMiss, CassetteProvider, interaction_key

EVALS = Path(__file__).resolve().parent / "evals"
FIXTURE = EVALS / "fixtures" / "mediocre-readme"
CASSETTE = EVALS / "cassettes" / "mediocre-readme.json"


# --- the offline eval (acceptance) ------------------------------------------ #

def test_panel_eval_replays_offline_and_reproducibly():
    provider = CassetteProvider(CASSETTE)  # replay mode; no network
    result = panel.review(str(FIXTURE), n_reviewers=3, provider=provider,
                          at="2026-01-01T00:00:00Z")
    # reproducible verdict: reviewer-2 is a no-go with a blocker
    assert result.consensus_go is False
    # reproducible discoveries: the usefulness blocker + the naming nit
    assert sorted(d.category for d in result.discoveries) == ["naming", "usefulness"]
    assert any(d.severity == "blocker" for d in result.discoveries)


def test_panel_eval_is_stable_across_runs():
    p1 = CassetteProvider(CASSETTE)
    p2 = CassetteProvider(CASSETTE)
    r1 = panel.review(str(FIXTURE), n_reviewers=3, provider=p1, at="2026-01-01T00:00:00Z")
    r2 = panel.review(str(FIXTURE), n_reviewers=3, provider=p2, at="2026-01-01T00:00:00Z")
    assert r1.consensus_go == r2.consensus_go
    assert [d.finding for d in r1.discoveries] == [d.finding for d in r2.discoveries]


# --- cassette layer ---------------------------------------------------------- #

def test_key_is_stable_and_context_sensitive():
    assert interaction_key("reviewer-1", "abc") == interaction_key("reviewer-1", "abc")
    assert interaction_key("reviewer-1", "abc") != interaction_key("reviewer-2", "abc")
    assert interaction_key("reviewer-1", "abc") != interaction_key("reviewer-1", "abd")


def test_record_then_replay_roundtrip(tmp_path):
    class Scripted:
        def review(self, reviewer_id, context, *, tools=None):
            return {"go": True, "rationale": reviewer_id, "findings": []}

    cassette = tmp_path / "c.json"
    rec = CassetteProvider(cassette, mode="record", inner=Scripted())
    rec.review("reviewer-1", "some context")
    rec.review("reviewer-2", "some context")
    rec.save()

    replay = CassetteProvider(cassette)
    assert replay.review("reviewer-1", "some context")["rationale"] == "reviewer-1"
    assert replay.review("reviewer-2", "some context")["rationale"] == "reviewer-2"


def test_replay_miss_raises_cassettemiss():
    provider = CassetteProvider(CASSETTE)
    with pytest.raises(CassetteMiss):
        provider.review("reviewer-1", "context that was never recorded")


def test_missing_cassette_file_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        CassetteProvider(tmp_path / "nope.json")


def test_record_requires_inner(tmp_path):
    with pytest.raises(ValueError):
        CassetteProvider(tmp_path / "c.json", mode="record")


def test_bad_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        CassetteProvider(tmp_path / "c.json", mode="bogus")


def test_committed_cassette_matches_fixture_context():
    # the committed keys must line up with what the current fixture produces,
    # or CI would silently miss and fall over — this guards against fixture drift
    context = panel.gather_context(str(FIXTURE))
    provider = CassetteProvider(CASSETTE)
    for i in range(1, 4):
        # each reviewer id resolves to a recorded interaction (no CassetteMiss)
        assert provider.review(f"reviewer-{i}", context)
