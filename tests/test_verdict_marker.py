"""Tests for the durable cross-repo verdict marker (issue #54).

No network and no live panel: these exercise the marker's render/parse contract,
SHA/slug detection against throwaway git repos, and the staleness sentinel.
"""
from __future__ import annotations

import subprocess

import pytest

from zenodotus import verdict_marker as vm


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   capture_output=True, text=True)


def _init_repo(path, *, remote: str | None = None) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("x\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    if remote:
        _git(path, "remote", "add", "origin", remote)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


# --- render ------------------------------------------------------------------ #

def test_render_contains_all_fields_in_a_single_comment_block():
    m = vm.render_verdict_marker(
        repo="Kromatic-Innovation/ideate-core", sha="a" * 40, verdict="warn",
        ran_at="2026-07-22T00:00:00Z", runner="zenodotus v1.2.3",
    )
    assert m.startswith("<!-- zenodotus-verdict: v1")
    assert m.rstrip().endswith("-->")
    assert "repo: Kromatic-Innovation/ideate-core" in m
    assert "sha: " + "a" * 40 in m
    assert "verdict: warn" in m
    assert "ran_at: 2026-07-22T00:00:00Z" in m
    assert "runner: zenodotus v1.2.3" in m


def test_render_defaults_runner_to_running_version():
    m = vm.render_verdict_marker(repo="o/n", sha="b" * 40, verdict="pass",
                                 ran_at="2026-07-22T00:00:00Z")
    assert "runner: zenodotus v" in m


@pytest.mark.parametrize("verdict", ["pass", "warn", "block"])
def test_render_accepts_every_three_state_verdict(verdict):
    m = vm.render_verdict_marker(repo="o/n", sha="c" * 40, verdict=verdict,
                                 ran_at="2026-07-22T00:00:00Z")
    assert f"verdict: {verdict}" in m


def test_render_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        vm.render_verdict_marker(repo="o/n", sha="d" * 40, verdict="conditional",
                                 ran_at="2026-07-22T00:00:00Z")


# --- parse / round-trip ------------------------------------------------------ #

def test_parse_round_trips_render():
    m = vm.render_verdict_marker(repo="o/n", sha="e" * 40, verdict="block",
                                 ran_at="2026-07-22T00:00:00Z", runner="zenodotus v9.9.9")
    parsed = vm.parse_verdict_marker(m)
    assert parsed == {
        "version": "v1", "repo": "o/n", "sha": "e" * 40, "verdict": "block",
        "ran_at": "2026-07-22T00:00:00Z", "runner": "zenodotus v9.9.9",
    }


def test_parse_finds_marker_embedded_in_surrounding_text():
    m = vm.render_verdict_marker(repo="o/n", sha="f" * 40, verdict="pass",
                                 ran_at="2026-07-22T00:00:00Z")
    body = f"Some human comment above.\n\n{m}\n\nAnd text below."
    parsed = vm.parse_verdict_marker(body)
    assert parsed is not None
    assert parsed["repo"] == "o/n"
    assert parsed["verdict"] == "pass"


def test_parse_returns_none_when_absent():
    assert vm.parse_verdict_marker("no marker here at all") is None
    assert vm.parse_verdict_marker("") is None


def test_parse_returns_none_on_missing_field():
    # drop the sha line — a partial marker must NOT read as a valid clearance
    m = vm.render_verdict_marker(repo="o/n", sha="a" * 40, verdict="pass",
                                 ran_at="2026-07-22T00:00:00Z")
    mangled = "\n".join(ln for ln in m.splitlines() if "sha:" not in ln)
    assert vm.parse_verdict_marker(mangled) is None


def test_parse_returns_none_on_out_of_vocabulary_verdict():
    m = vm.render_verdict_marker(repo="o/n", sha="a" * 40, verdict="warn",
                                 ran_at="2026-07-22T00:00:00Z")
    assert vm.parse_verdict_marker(m.replace("verdict: warn", "verdict: fail")) is None


# --- sha / slug detection ---------------------------------------------------- #

def test_head_sha_returns_unknown_for_non_git_path(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert vm.head_sha(d) == vm.UNKNOWN_SHA


def test_head_sha_returns_commit_for_git_repo(tmp_path):
    sha = _init_repo(tmp_path / "repo")
    assert vm.head_sha(tmp_path / "repo") == sha
    assert len(sha) == 40


@pytest.mark.parametrize("url,slug", [
    ("https://github.com/Kromatic-Innovation/ideate-core.git", "Kromatic-Innovation/ideate-core"),
    ("https://github.com/Kromatic-Innovation/ideate-core", "Kromatic-Innovation/ideate-core"),
    ("git@github.com:Kromatic-Innovation/panelist.git", "Kromatic-Innovation/panelist"),
])
def test_detect_repo_slug_parses_github_remotes(tmp_path, url, slug):
    _init_repo(tmp_path / "repo", remote=url)
    assert vm.detect_repo_slug(tmp_path / "repo") == slug


def test_detect_repo_slug_none_without_remote(tmp_path):
    _init_repo(tmp_path / "repo")
    assert vm.detect_repo_slug(tmp_path / "repo") is None


def test_resolve_repo_prefers_override_then_remote_then_dirname(tmp_path):
    _init_repo(tmp_path / "repo", remote="https://github.com/o/detected.git")
    # explicit override wins
    assert vm.resolve_repo(tmp_path / "repo", "o/override") == "o/override"
    # else the detected remote
    assert vm.resolve_repo(tmp_path / "repo") == "o/detected"
    # else the directory name (non-git path)
    plain = tmp_path / "plainname"
    plain.mkdir()
    assert vm.resolve_repo(plain) == "plainname"


def test_runner_string_shape():
    assert vm.runner_string().startswith("zenodotus v")
