"""Tests for the CI leak self-check.

Includes a guard that THIS repo is clean under the default denylist — the check
CI runs must be green (issue #11 acceptance).
"""
from __future__ import annotations

from pathlib import Path

from zenodotus import leakcheck
from zenodotus.leakcheck import scan


def test_clean_repo_has_no_hits(tmp_path):
    (tmp_path / "README.md").write_text("# A perfectly public project.\n")
    (tmp_path / "app.py").write_text("import os\nprint('hello world')\n")
    assert scan(tmp_path) == []


def test_detects_home_dir_dev_path(tmp_path):
    (tmp_path / "notes.md").write_text("built from ~/Code/secret-project/thing\n")
    hits = scan(tmp_path)
    assert len(hits) == 1
    assert hits[0].file == "notes.md"
    assert hits[0].line == 1
    assert "dev path" in hits[0].label


def test_detects_macos_dev_path(tmp_path):
    (tmp_path / "log.txt").write_text("/Users/alice/Projects/private-repo/build\n")
    assert any("macOS" in h.label for h in scan(tmp_path))


def test_detects_internal_hostname(tmp_path):
    (tmp_path / "config.yaml").write_text("host: jenkins.corp\napi: metrics.internal\n")
    hits = scan(tmp_path)
    labels = {h.label for h in hits}
    assert "internal hostname" in labels
    assert len(hits) == 2


def test_per_repo_denylist_file_adds_patterns(tmp_path):
    (tmp_path / "team.md").write_text("Reviewed by J. Employee-Name.\n")
    (tmp_path / ".zenodotus-leakcheck.txt").write_text(
        "# internal reviewers\nEmployee-Name\n"
    )
    hits = scan(tmp_path)
    assert len(hits) == 1
    assert hits[0].label.startswith("denylist:")


def test_denylist_file_itself_is_not_scanned(tmp_path):
    # the config lists patterns; scanning it would self-flag every entry
    (tmp_path / ".zenodotus-leakcheck.txt").write_text("acme.corp\n")
    (tmp_path / "clean.md").write_text("nothing internal here\n")
    assert scan(tmp_path) == []


def test_extra_patterns_argument(tmp_path):
    (tmp_path / "x.md").write_text("PROJECT-CODENAME-FALCON is secret\n")
    hits = scan(tmp_path, patterns=[(r"CODENAME-\w+", "codename")])
    assert any(h.label == "codename" for h in hits)


def test_binary_and_ignored_dirs_skipped(tmp_path):
    (tmp_path / "img.png").write_bytes(b"\x00\x01~/Code/leak\x00")
    vend = tmp_path / ".venv"
    vend.mkdir()
    (vend / "junk.py").write_text("~/Code/whatever\n")
    assert scan(tmp_path) == []


def test_main_exit_codes(tmp_path, capsys):
    (tmp_path / "clean.md").write_text("all public\n")
    assert leakcheck.main([str(tmp_path)]) == 0
    (tmp_path / "leak.md").write_text("path: ~/Code/oops\n")
    assert leakcheck.main([str(tmp_path)]) == 1


def test_main_json_output(tmp_path, capsys):
    (tmp_path / "leak.md").write_text("host: build.internal\n")
    rc = leakcheck.main([str(tmp_path), "--json"])
    assert rc == 1
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean"] is False
    assert len(payload["hits"]) == 1


def test_this_repo_is_clean():
    """Acceptance guard (#11): the zenodotus repo passes its own leak-check."""
    repo_root = Path(__file__).resolve().parent.parent
    hits = scan(repo_root)
    assert hits == [], f"leak-check found internal markers in this repo: {hits}"
