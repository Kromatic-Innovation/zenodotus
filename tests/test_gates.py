"""Tests for the deterministic pre-gates.

External tools (gitleaks, pyroma, licensee, scorecard) are NOT required to run
these tests: the subprocess seams (``_which`` / ``_run``) are monkeypatched so
the gate logic is exercised deterministically and offline, and the
graceful-degradation path (tool absent) is asserted directly.
"""
from __future__ import annotations

import subprocess

import pytest

from zenodotus import gates
from zenodotus.gates import GateResult

# --- fixture repos ----------------------------------------------------------- #

def _make_repo(root, *, license=True, contributing=True, readme=True,
               coc=False, security=False, secret=False):
    if readme:
        (root / "README.md").write_text("# Example\nA useful thing.\n")
    if license:
        (root / "LICENSE").write_text("Apache License 2.0\n")
    if contributing:
        (root / "CONTRIBUTING.md").write_text("# Contributing\n")
    if coc:
        (root / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n")
    if security:
        (root / "SECURITY.md").write_text("# Security policy\n")
    if secret:
        (root / "config.py").write_text('AWS_SECRET = "AKIAIOSFODNN7EXAMPLE"\n')
    return root


@pytest.fixture
def clean_repo(tmp_path):
    d = tmp_path / "clean"
    d.mkdir()
    return _make_repo(d, coc=True, security=True)


@pytest.fixture
def missing_license_repo(tmp_path):
    d = tmp_path / "nolicense"
    d.mkdir()
    return _make_repo(d, license=False)


@pytest.fixture
def planted_secret_repo(tmp_path):
    d = tmp_path / "secret"
    d.mkdir()
    return _make_repo(d, secret=True)


# --- helpers to fake external tools ----------------------------------------- #

def _no_tools(monkeypatch):
    monkeypatch.setattr(gates, "_which", lambda tool: None)


def _fake_tool(monkeypatch, present, returncode=0, stdout="", stderr=""):
    monkeypatch.setattr(gates, "_which", lambda tool: f"/usr/bin/{tool}" if tool in present else None)

    def fake_run(cmd, cwd=None):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(gates, "_run", fake_run)


# --- license_present --------------------------------------------------------- #

def test_license_present_clean(clean_repo, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.license_present(str(clean_repo))
    assert r.passed and not r.skipped
    assert "LICENSE" in r.detail


def test_license_present_missing(missing_license_repo, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.license_present(str(missing_license_repo))
    assert not r.passed
    assert "no LICENSE" in r.detail


def test_license_present_matches_copying_and_extensions(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = tmp_path / "cp"
    d.mkdir()
    (d / "COPYING.txt").write_text("GPL\n")
    (d / "README.md").write_text("# x\n")
    assert gates.license_present(str(d)).passed


def test_license_present_uses_licensee_when_available(clean_repo, monkeypatch):
    _fake_tool(monkeypatch, present={"licensee"}, returncode=0, stdout='{"license":"Apache-2.0"}')
    r = gates.license_present(str(clean_repo))
    assert r.passed
    assert r.data.get("licensee") == "identified"


# --- community_files --------------------------------------------------------- #

def test_community_files_clean_all_present(clean_repo, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.community_files(str(clean_repo))
    assert r.passed
    assert r.data["present"]["README"] and r.data["present"]["SECURITY"]


def test_community_files_missing_required_fails(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = tmp_path / "noreq"
    d.mkdir()
    _make_repo(d, contributing=False)  # README only, no CONTRIBUTING
    r = gates.community_files(str(d))
    assert not r.passed
    assert "CONTRIBUTING" in r.data["missing_required"]


def test_community_files_recommended_missing_still_passes(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = tmp_path / "rec"
    d.mkdir()
    _make_repo(d)  # README + CONTRIBUTING + LICENSE, but no CoC/SECURITY
    r = gates.community_files(str(d))
    assert r.passed
    assert "recommended missing" in r.detail


# --- no_secrets -------------------------------------------------------------- #

def test_no_secrets_skips_without_gitleaks(planted_secret_repo, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.no_secrets(str(planted_secret_repo))
    assert r.skipped and not r.passed
    assert "gitleaks" in r.detail.lower()


def test_no_secrets_clean_when_gitleaks_reports_none(clean_repo, monkeypatch):
    _fake_tool(monkeypatch, present={"gitleaks"}, returncode=0)
    r = gates.no_secrets(str(clean_repo))
    assert r.passed and not r.skipped


def test_no_secrets_fails_when_gitleaks_finds_leak(planted_secret_repo, monkeypatch):
    _fake_tool(monkeypatch, present={"gitleaks"}, returncode=1)
    r = gates.no_secrets(str(planted_secret_repo))
    assert not r.passed and not r.skipped
    assert r.data["exit_code"] == 1


def test_no_secrets_reports_tool_error(clean_repo, monkeypatch):
    _fake_tool(monkeypatch, present={"gitleaks"}, returncode=2, stderr="boom")
    r = gates.no_secrets(str(clean_repo))
    assert not r.passed
    assert "errored" in r.detail


# --- packaging_ok ------------------------------------------------------------ #

def _python_repo(tmp_path):
    d = tmp_path / "py"
    d.mkdir()
    (d / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1.0'\n")
    return d


def _npm_repo(tmp_path, pkg='{"name":"x","version":"0.1.0","description":"d","license":"MIT","repository":"r"}'):
    d = tmp_path / "npm"
    d.mkdir()
    (d / "package.json").write_text(pkg)
    return d


def test_packaging_ok_skips_without_manifest(clean_repo, monkeypatch):
    # clean_repo has no pyproject/package.json — no ecosystem to gate, so skip
    # gracefully rather than hard-failing (the #41 regression: pyroma vs JS).
    _no_tools(monkeypatch)
    r = gates.packaging_ok(str(clean_repo))
    assert r.skipped and not r.passed
    assert r.data["ecosystem"] == "none"


def test_packaging_ok_python_skips_without_pyroma(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.packaging_ok(str(_python_repo(tmp_path)))
    assert r.skipped and not r.passed
    assert "pyroma" in r.detail


def test_packaging_ok_python_pass_and_fail(tmp_path, monkeypatch):
    d = _python_repo(tmp_path)
    _fake_tool(monkeypatch, present={"pyroma"}, returncode=0, stdout="Final rating: 9/10")
    r = gates.packaging_ok(str(d))
    assert r.passed and r.data["ecosystem"] == "python"
    _fake_tool(monkeypatch, present={"pyroma"}, returncode=1, stdout="Final rating: 3/10")
    assert not gates.packaging_ok(str(d)).passed


def test_packaging_ok_npm_recognized_and_not_hardfailed(tmp_path, monkeypatch):
    # the #41 core bug: a JS repo used to hard-fail via pyroma. Now it is gated
    # as npm and a clean package.json passes without any tool installed.
    _no_tools(monkeypatch)
    r = gates.packaging_ok(str(_npm_repo(tmp_path)))
    assert r.passed and not r.skipped
    assert r.data["ecosystem"] == "npm"
    assert "npm not installed" in r.detail


def test_packaging_ok_npm_missing_required_field_fails(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = _npm_repo(tmp_path, pkg='{"name":"x"}')  # no version
    r = gates.packaging_ok(str(d))
    assert not r.passed and not r.skipped
    assert "version" in r.data["missing_required"]


def test_packaging_ok_npm_private_is_skipped(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = _npm_repo(tmp_path, pkg='{"name":"x","version":"1.0.0","private":true}')
    r = gates.packaging_ok(str(d))
    assert r.skipped and not r.passed
    assert r.data["private"] is True


def test_packaging_ok_npm_runs_pack_when_npm_available(tmp_path, monkeypatch):
    d = _npm_repo(tmp_path)
    _fake_tool(monkeypatch, present={"npm"}, returncode=0, stdout="x-0.1.0.tgz")
    r = gates.packaging_ok(str(d))
    assert r.passed and r.data["npm_pack_exit"] == 0
    _fake_tool(monkeypatch, present={"npm"}, returncode=1, stderr="npm ERR! no name")
    assert not gates.packaging_ok(str(d)).passed


def test_packaging_ok_unsupported_ecosystem_skips_gracefully(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    d = tmp_path / "go"
    d.mkdir()
    (d / "go.mod").write_text("module example.com/x\n")
    r = gates.packaging_ok(str(d))
    assert r.skipped and not r.passed
    assert r.data["ecosystem"] == "go"


# --- security_posture (optional) -------------------------------------------- #

def test_security_posture_skipped_without_scorecard(clean_repo, monkeypatch):
    _no_tools(monkeypatch)
    r = gates.security_posture(str(clean_repo))
    assert r.skipped


# --- run_all / floor_passed -------------------------------------------------- #

def test_run_all_never_crashes_without_tools(clean_repo, monkeypatch):
    _no_tools(monkeypatch)
    results = gates.run_all(str(clean_repo))
    names = {r.name for r in results}
    assert {"license_present", "community_files", "no_secrets", "packaging_ok"} <= names
    # optional gate excluded by default
    assert "security_posture" not in names


def test_run_all_includes_optional_when_requested(clean_repo, monkeypatch):
    _no_tools(monkeypatch)
    results = gates.run_all(str(clean_repo), include_optional=True)
    assert any(r.name == "security_posture" for r in results)


def test_run_all_reports_gate_exceptions_without_aborting(clean_repo, monkeypatch):
    _no_tools(monkeypatch)

    def boom(path):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(gates, "license_present", boom)
    # rebuild the required-gate tuple so the patched func is used
    monkeypatch.setattr(gates, "_REQUIRED_GATES",
                        (gates.license_present, gates.community_files))
    results = gates.run_all(str(clean_repo))
    raised = next(r for r in results if "kaboom" in r.detail)
    assert not raised.passed
    assert "RuntimeError" in raised.detail


def test_floor_passed_ignores_skipped(clean_repo):
    results = [
        GateResult("a", True, "ok"),
        GateResult("b", False, "tool absent", skipped=True),
    ]
    assert gates.floor_passed(results) is True
    results.append(GateResult("c", False, "real failure"))
    assert gates.floor_passed(results) is False
