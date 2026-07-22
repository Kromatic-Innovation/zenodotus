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
# Advisory-only: findings present (major/minor) but the reviewer still says go —
# the WARN case. Never a blocker, so it must never block regardless of --fail-on.
_WARN = {
    "go": True,
    "rationale": "minor nits, ship-able",
    "findings": [{"finding": "README could document the config format", "category": "doc-quality",
                  "severity": "major", "rationale": "an outsider has to guess it"}],
}


# --- floor short-circuit ----------------------------------------------------- #

def test_floor_failure_short_circuits_and_exits_nonzero(tmp_path, capsys):
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    (d / "CONTRIBUTING.md").write_text("# c\n")
    # no LICENSE => license_present fails => floor fails => panel never runs.
    # A deterministic floor failure is a genuine BLOCK regardless of --fail-on.
    code = main(["review", str(d), "--log", ""], provider=StubProvider(_GO), now=NOW)
    assert code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "Panel: not run" in out
    assert "VERDICT: BLOCK" in out


def test_floor_failure_blocks_even_with_fail_on_never(tmp_path, capsys):
    # --fail-on governs only the panel; the deterministic floor still hard-blocks.
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    (d / "CONTRIBUTING.md").write_text("# c\n")
    code = main(["review", str(d), "--fail-on", "never", "--log", ""],
                provider=StubProvider(_GO), now=NOW)
    assert code == 1
    assert "VERDICT: BLOCK" in capsys.readouterr().out


# --- full pipeline: pass ----------------------------------------------------- #

def test_clean_repo_pass_exits_zero(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--reviewers", "3", "--log", ""],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    out = capsys.readouterr().out
    assert "floor: PASSED" in out
    assert "VERDICT: PASS" in out


# --- full pipeline: warn (advisory) ------------------------------------------ #

def test_advisory_findings_warn_and_exit_zero_by_default(tmp_path, capsys):
    # major/minor findings with a reviewer go => WARN, exit 0, warnings advisory.
    d = _clean_repo(tmp_path)
    log = tmp_path / "discoveries.jsonl"
    code = main(["review", str(d), "--reviewers", "2", "--log", str(log)],
                provider=StubProvider(_WARN), now=NOW)
    assert code == 0
    out = capsys.readouterr().out
    assert "VERDICT: WARN" in out
    assert "do NOT block" in out  # explicitly labeled non-blocking
    rows = load(log)
    assert len(rows) == 2  # one finding x 2 reviewers still logged as discoveries


def test_panel_blocker_is_advisory_by_default(tmp_path, capsys):
    # Default --fail-on never: even a panel BLOCKER only WARNs (exit 0), but the
    # discoveries are still logged and the raw block signal stays visible.
    d = _clean_repo(tmp_path)
    log = tmp_path / "discoveries.jsonl"
    code = main(["review", str(d), "--reviewers", "2", "--log", str(log)],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 0  # advisory by default — panel findings never block
    out = capsys.readouterr().out
    assert "VERDICT: WARN" in out
    assert "blocking is disabled via --fail-on never" in out
    rows = load(log)
    assert len(rows) == 2
    assert rows[0]["at"] == NOW


# --- full pipeline: block (opt-in via --fail-on blocker) --------------------- #

def test_panel_blocker_blocks_with_fail_on_blocker(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    log = tmp_path / "discoveries.jsonl"
    code = main(["review", str(d), "--fail-on", "blocker", "--reviewers", "2", "--log", str(log)],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 1
    out = capsys.readouterr().out
    assert "VERDICT: BLOCK" in out
    rows = load(log)
    assert len(rows) == 2
    assert all(r["missed_by_deterministic"] is True for r in rows)


def test_advisory_findings_never_block_even_with_fail_on_blocker(tmp_path, capsys):
    # a reviewer no-go / blocker escalates under --fail-on blocker, but plain
    # major/minor advisory findings (go=True) must NEVER block.
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--fail-on", "blocker", "--reviewers", "2", "--log", ""],
                provider=StubProvider(_WARN), now=NOW)
    assert code == 0
    assert "VERDICT: WARN" in capsys.readouterr().out


# --- --json output ----------------------------------------------------------- #

def test_json_output_is_parseable(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--json", "--reviewers", "1", "--log", ""],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass"
    assert payload["state"] == "pass"  # spec §1.2 field-name alias
    assert payload["floor_passed"] is True
    assert payload["panel"]["consensus_go"] is True  # back-compat field retained
    assert len(payload["panel"]["verdicts"]) == 1
    assert {g["name"] for g in payload["gates"]} >= {"license_present", "community_files"}


def test_json_three_states(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    # pass
    main(["review", str(d), "--json", "--reviewers", "1", "--log", ""],
         provider=StubProvider(_GO), now=NOW)
    assert json.loads(capsys.readouterr().out)["verdict"] == "pass"
    # warn (advisory findings, default fail-on never)
    main(["review", str(d), "--json", "--reviewers", "1", "--log", ""],
         provider=StubProvider(_WARN), now=NOW)
    warn = json.loads(capsys.readouterr().out)
    assert warn["verdict"] == "warn"
    assert warn["panel_verdict"] == "warn"
    # block (panel blocker + opt-in --fail-on blocker); panel_verdict stays block
    main(["review", str(d), "--json", "--fail-on", "blocker", "--reviewers", "1", "--log", ""],
         provider=StubProvider(_NOGO), now=NOW)
    block = json.loads(capsys.readouterr().out)
    assert block["verdict"] == "block"
    assert block["panel_verdict"] == "block"
    # same blocker under default never: effective warn, but raw panel_verdict block
    main(["review", str(d), "--json", "--reviewers", "1", "--log", ""],
         provider=StubProvider(_NOGO), now=NOW)
    downgraded = json.loads(capsys.readouterr().out)
    assert downgraded["verdict"] == "warn"
    assert downgraded["panel_verdict"] == "block"


# --- shadow mode (#9) -------------------------------------------------------- #

def test_shadow_never_fails_even_on_panel_nogo(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    log = tmp_path / "discoveries.jsonl"
    code = main(["review", str(d), "--shadow", "--reviewers", "2", "--log", str(log)],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 0  # shadow mode never blocks the build
    out = capsys.readouterr().out
    assert "SHADOW" in out
    # shadow is folded into the three-state model as warn-only: a would-be block
    # is presented as WARN (advisory), never BLOCK.
    assert "VERDICT: WARN" in out
    assert "VERDICT: BLOCK" not in out
    rows = load(log)
    assert len(rows) == 2  # discoveries still accumulated


def test_shadow_runs_panel_even_when_floor_fails(tmp_path):
    # a floor-failing RC still gets panel evidence in shadow mode
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    (d / "CONTRIBUTING.md").write_text("# c\n")  # no LICENSE => floor fails
    log = tmp_path / "d.jsonl"
    code = main(["review", str(d), "--shadow", "--reviewers", "1", "--log", str(log)],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 0
    rows = load(log)
    assert len(rows) == 1  # panel ran despite floor failure; evidence logged


def test_shadow_json_marks_shadow_and_forces_exit_zero(tmp_path, capsys):
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    code = main(["review", str(d), "--shadow", "--json", "--reviewers", "1", "--log", ""],
                provider=StubProvider(_NOGO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["shadow"] is True
    assert payload["floor_passed"] is False
    assert payload["panel"] is not None  # panel ran in shadow mode
    assert payload["verdict"] == "warn"  # shadow = warn-only, never block


def test_non_shadow_still_short_circuits(tmp_path):
    # regression: without --shadow, a floor-fail still skips the panel
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    log = tmp_path / "d.jsonl"
    code = main(["review", str(d), "--log", str(log)], provider=StubProvider(_NOGO), now=NOW)
    assert code == 1
    assert not log.exists() or load(log) == []


def test_json_floor_fail_has_null_panel(tmp_path, capsys):
    d = tmp_path / "bare"
    d.mkdir()
    (d / "README.md").write_text("# x\n")  # missing LICENSE + CONTRIBUTING
    code = main(["review", str(d), "--json", "--log", ""], provider=StubProvider(_GO), now=NOW)
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["floor_passed"] is False
    assert payload["panel"] is None
    assert payload["panel_verdict"] is None  # panel did not run
    assert payload["verdict"] == "block"  # deterministic floor failure blocks


# --- durable cross-repo verdict marker (#54) --------------------------------- #

def _git(path, *args):
    import subprocess
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


def _make_git_repo(d, remote="https://github.com/o/target.git"):
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    _git(d, "remote", "add", "origin", remote)
    import subprocess
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_no_marker_by_default(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--json", "--log", ""], provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict_marker"] is None


def test_emit_verdict_marker_records_head_sha_and_verdict(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    sha = _make_git_repo(d)
    code = main(["review", str(d), "--json", "--log", "", "--emit-verdict-marker"],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    marker = payload["verdict_marker"]
    assert marker is not None
    from zenodotus.verdict_marker import parse_verdict_marker
    parsed = parse_verdict_marker(marker)
    assert parsed["sha"] == sha
    assert parsed["repo"] == "o/target"          # detected from origin remote
    assert parsed["verdict"] == payload["verdict"]  # matches the effective verdict
    assert parsed["ran_at"] == NOW


def test_emit_verdict_marker_repo_override(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    _make_git_repo(d)
    code = main(["review", str(d), "--json", "--log", "", "--emit-verdict-marker",
                 "--repo", "Kromatic-Innovation/ideate-core"],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    from zenodotus.verdict_marker import parse_verdict_marker
    assert parse_verdict_marker(payload["verdict_marker"])["repo"] == "Kromatic-Innovation/ideate-core"


def test_emit_verdict_marker_non_git_path_uses_unknown_sha(tmp_path, capsys):
    # a non-git tree can't pin a commit -> sentinel sha so a consumer never reads
    # it as a false "cleared" (staleness fallback, design Q5).
    d = _clean_repo(tmp_path)
    code = main(["review", str(d), "--json", "--log", "", "--emit-verdict-marker"],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    from zenodotus.verdict_marker import parse_verdict_marker, UNKNOWN_SHA
    assert parse_verdict_marker(payload["verdict_marker"])["sha"] == UNKNOWN_SHA


def test_emit_verdict_marker_on_floor_fail_records_block(tmp_path, capsys):
    # marker is emitted even when the floor fails (verdict=block) via the
    # short-circuit path — a block is a valid durable verdict to record.
    d = tmp_path / "nolicense"
    d.mkdir()
    (d / "README.md").write_text("# x\n")
    code = main(["review", str(d), "--json", "--log", "", "--emit-verdict-marker"],
                provider=StubProvider(_GO), now=NOW)
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    from zenodotus.verdict_marker import parse_verdict_marker
    assert parse_verdict_marker(payload["verdict_marker"])["verdict"] == "block"


def test_emit_verdict_marker_printed_in_human_mode(tmp_path, capsys):
    d = _clean_repo(tmp_path)
    _make_git_repo(d)
    code = main(["review", str(d), "--log", "", "--emit-verdict-marker"],
                provider=StubProvider(_GO), now=NOW)
    assert code == 0
    out = capsys.readouterr().out
    assert "<!-- zenodotus-verdict: v1" in out
    assert "oss-status" in out
