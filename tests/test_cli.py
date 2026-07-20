"""End-to-end tests for the ``zenodotus review`` CLI.

Runs the full pipeline against fixture repos with a stub reviewer provider and
external gate tools disabled — no live API calls, no tools required.
"""
from __future__ import annotations

import json

import pytest

from zenodotus import gates
from zenodotus.cli import main
from zenodotus.discovery_log import load

NOW = "2026-07-20T00:00:00Z"


class StubProvider:
    def __init__(self, verdict):
        self._verdict = verdict

    def review(self, reviewer_id, context):
        return self._verdict


@pytest.fixture(autouse=True)
def no_external_tools(monkeypatch):
    # deterministic floor: subprocess-backed gates skip, so the floor depends
    # only on the pure-Python license/community checks.
    monkeypatch.setattr(gates, "_which", lambda tool: None)


def _clean_repo(tmp_path):
    d = tmp_path / "clean"
    d.mkdir()
    (d / "README.md").write_text("# Thing\nA genuinely useful public thing.\n")
    (d / "LICENSE").write_text("Apache License 2.0\n")
    (d / "CONTRIBUTING.md").write_text("# Contributing\n")
    return d


_GO = {"go": True, "rationale": "ready", "findings": []}
_NOGO = {
    "go": False,
    "rationale": "not ready",
    "findings": [{"finding": "README assumes internal context", "category": "coherence",
                  "severity": "blocker", "rationale": "outsider can't follow"}],
}


# --- floor short-circuit ----------------------------------------------------- #

def test_floor_failure_short_circuits_and_exits_nonzero(tmp_path, capsys):
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    (d / "CONTRIBUTING.md").write_text("# c\n")
    # no LICENSE => license_present fails => floor fails => panel never runs
    code = main(["review", str(d), "--log", ""], provider=StubProvider(_GO), now=NOW)
    assert code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "Panel: not run" in out
    assert "VERDICT: NO-GO" in out


# --- full pipeline: go ------------------------------------------------------- #

def test_clean_repo_go_exits_zero(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--reviewers", "3", "--log", ""],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    out = capsys.readouterr().out
    assert "floor: PASSED" in out
    assert "VERDICT: GO" in out


# --- full pipeline: no-go with discoveries ----------------------------------- #

def test_panel_nogo_logs_discoveries_and_exits_nonzero(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    log = tmp_path / "discoveries.jsonl"
    code = main(["review", str(d), "--reviewers", "2", "--log", str(log)],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 1
    out = capsys.readouterr().out
    assert "VERDICT: NO-GO" in out
    rows = load(log)
    assert len(rows) == 2  # one finding x 2 reviewers
    assert all(r["missed_by_deterministic"] is True for r in rows)
    assert rows[0]["at"] == NOW


# --- --json output ----------------------------------------------------------- #

def test_json_output_is_parseable(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--json", "--reviewers", "1", "--log", ""],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "go"
    assert payload["floor_passed"] is True
    assert payload["panel"]["consensus_go"] is True
    assert len(payload["panel"]["verdicts"]) == 1
    assert {g["name"] for g in payload["gates"]} >= {"license_present", "community_files"}


def test_json_floor_fail_has_null_panel(tmp_path, capsys):
    d = tmp_path / "bare"
    d.mkdir()
    (d / "README.md").write_text("# x\n")  # missing LICENSE + CONTRIBUTING
    code = main(["review", str(d), "--json", "--log", ""], provider=StubProvider(_GO), now=NOW)
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["floor_passed"] is False
    assert payload["panel"] is None
    assert payload["verdict"] == "no-go"
