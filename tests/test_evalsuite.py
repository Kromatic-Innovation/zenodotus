"""Tests for the eval suite (issue #5) — the second prove-itself gate.

The suite runs the real panel over discovery-derived fixtures using committed
cassettes, fully offline, and asserts each fixture reproduces its expected
verdict. This file guards that the suite is green and reproducible in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

# suite.py lives beside the fixtures/cassettes it indexes (tests/evals/); make it
# importable without turning tests/ into a package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "evals"))

import suite  # noqa: E402


def test_eval_suite_is_green():
    results = suite.run_suite()
    failures = [f"{r.name}: {r.detail}" for r in results if not r.ok]
    assert not failures, f"eval suite not green: {failures}"
    assert suite.suite_passed(results) is True


def test_eval_suite_covers_both_a_block_and_a_pass():
    # a meaningful suite must exercise BOTH outcomes: a repo the panel correctly
    # blocks, and a repo it correctly passes (the #30 false-blocker regression).
    by_name = {c.name: c for c in suite.EVAL_CASES}
    assert by_name["mediocre-readme"].expect_go is False
    assert by_name["clean-complete"].expect_go is True


def test_eval_suite_covers_all_three_verdict_states():
    # the three-state model (#31) is only proven if the suite pins each pole.
    verdicts = {c.name: c.expect_verdict for c in suite.EVAL_CASES}
    assert verdicts["clean-complete"] == "pass"
    assert verdicts["warn-advisory"] == "warn"
    assert verdicts["mediocre-readme"] == "block"
    # and the panel actually reproduces each state end to end
    by_name = {r.name: r for r in suite.run_suite()}
    assert by_name["clean-complete"].verdict == "pass"
    assert by_name["warn-advisory"].verdict == "warn"
    assert by_name["mediocre-readme"].verdict == "block"


def test_warn_advisory_warns_without_blocking():
    # the middle state: advisory findings, a reviewer go, no blocker => warn.
    result = suite.run_case(next(c for c in suite.EVAL_CASES if c.name == "warn-advisory"))
    assert result.ok
    assert result.consensus_go is True
    assert result.has_blocker is False
    assert result.verdict == "warn"
    assert result.categories == ["doc-quality", "naming"]


def test_eval_suite_is_reproducible_across_runs():
    r1 = suite.run_suite()
    r2 = suite.run_suite()
    assert [(r.name, r.consensus_go, r.verdict, r.categories, r.has_blocker) for r in r1] == \
           [(r.name, r.consensus_go, r.verdict, r.categories, r.has_blocker) for r in r2]


def test_clean_complete_reproduces_no_false_blocker():
    # regression for the tickle-stick/athenaeum themes (#30): a complete, well-
    # licensed repo passes cleanly — no truncation/license false blocker.
    result = suite.run_case(next(c for c in suite.EVAL_CASES if c.name == "clean-complete"))
    assert result.ok
    assert result.consensus_go is True
    assert result.has_blocker is False
    assert result.categories == []


def test_pre_publish_registry_lag_never_blocks():
    # regression for #53: a pre-publish candidate whose docs advertise the
    # about-to-ship version while the live registry still lags the previous one
    # must NOT be blocked. The lag is expected/structural, not a defect — the
    # panel reports it as at most an advisory release-day note (WARN, exit 0).
    result = suite.run_case(
        next(c for c in suite.EVAL_CASES if c.name == "pre-publish-registry-lag")
    )
    assert result.ok
    assert result.consensus_go is True
    assert result.has_blocker is False
    assert result.verdict == "warn"
    assert result.verdict != "block"
    assert result.categories == ["doc-quality"]


def test_mediocre_readme_still_blocks():
    # the genuine-problem case must still be caught, or the suite proves nothing.
    result = suite.run_case(next(c for c in suite.EVAL_CASES if c.name == "mediocre-readme"))
    assert result.ok
    assert result.consensus_go is False
    assert result.has_blocker is True
    assert result.categories == ["naming", "usefulness"]


def test_suite_main_returns_zero_when_green(capsys):
    rc = suite.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "eval suite: GREEN" in out
