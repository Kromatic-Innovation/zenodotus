"""Tests for the CI leak self-check.

Includes a guard that THIS repo is clean under the default denylist — the check
CI runs must be green (issue #11 acceptance).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from zenodotus import leakcheck
from zenodotus.leakcheck import scan


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


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


def test_gitignored_file_with_leak_is_not_scanned(tmp_path):
    """Regression (#68): inside a git work tree, leakcheck respects .gitignore.

    A gitignored file containing a known leak marker must NOT trip the check (it
    can never ship); a tracked file with the same marker still must. Before #68,
    ``leakcheck`` walked the raw tree with ``rglob`` and flagged the ignored one —
    a false positive on any locally-generated artifact.
    """
    if shutil.which("git") is None:  # pragma: no cover - git is a CI dep
        pytest.skip("git not available")

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    # A gitignored generated artifact carrying a leak marker — must be skipped.
    (tmp_path / ".gitignore").write_text(".agents/\n")
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "workspace-context.md").write_text("built from ~/Code/private/thing\n")

    # A tracked file carrying the same marker — must still be caught.
    (tmp_path / "notes.md").write_text("path: ~/Code/also-here\n")
    _git(tmp_path, "add", ".gitignore", "notes.md")

    hits = scan(tmp_path)
    files = {h.file for h in hits}
    assert "notes.md" in files, f"tracked leak must still be caught; got {hits}"
    assert not any(h.file.startswith(".agents/") for h in hits), (
        f"gitignored file must not be scanned; got {hits}"
    )


def test_untracked_file_with_leak_is_not_scanned(tmp_path):
    """A plain untracked (not even ignored) file also doesn't ship, so it's skipped."""
    if shutil.which("git") is None:  # pragma: no cover - git is a CI dep
        pytest.skip("git not available")

    _git(tmp_path, "init", "-q")
    (tmp_path / "shipped.md").write_text("clean and public\n")
    _git(tmp_path, "add", "shipped.md")
    # Never added to the index — untracked, so it would not ship.
    (tmp_path / "scratch.md").write_text("leftover: ~/Code/scratch\n")

    assert scan(tmp_path) == []


def test_this_repo_is_clean():
    """Acceptance guard (#11): the zenodotus repo passes its own leak-check."""
    repo_root = Path(__file__).resolve().parent.parent
    hits = scan(repo_root)
    assert hits == [], f"leak-check found internal markers in this repo: {hits}"


def test_tracked_build_artifact_with_leak_is_scanned(tmp_path):
    """Regression (#106): a *tracked* build artifact is not exempt from scanning.

    ``leakcheck`` used to apply a private ``_IGNORE_DIRS`` set as a second filter
    on top of ``fileset.shippable_files``, dropping any path with a ``dist``,
    ``build`` or ``node_modules`` component *even when git tracked it*. A
    committed sdist/wheel carrying an absolute developer path — one of the more
    likely places for one to end up — was therefore never scanned.

    Counter-example property this test must have (#106 acceptance): reintroducing
    that second directory filter makes this test FAIL, so it pins the behaviour
    rather than the current shape of the code.
    """
    if shutil.which("git") is None:  # pragma: no cover - git is a CI dep
        pytest.skip("git not available")

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    tracked = ["dist/wheel-manifest.txt", "build/lib/meta.txt", "node_modules/pkg/info.txt"]
    for rel in tracked:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"built from ~/Code/private/{rel}\n")
        _git(tmp_path, "add", rel)

    hits = scan(tmp_path)
    assert {h.file for h in hits} == set(tracked), (
        f"tracked build artifacts are shipped content and must be scanned; got {hits}"
    )


def test_non_git_fallback_still_skips_build_dirs(tmp_path):
    """(#106) Outside a git work tree the fallback walk still skips build/venv dirs.

    Removing leakcheck's private ``_IGNORE_DIRS`` must not widen the *non-git*
    path: there is no index to be authoritative, so ``fileset.walk_files`` keeps
    filtering generated-artifact directories by name.
    """
    for rel in ("dist/wheel.txt", "build/lib.txt", ".venv/junk.py", "node_modules/x.js"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("built from ~/Code/private/thing\n")
    (tmp_path / "README.md").write_text("# public\n")

    assert scan(tmp_path) == []


# --- the denylist exemption follows the argument, not a fixed name (issue #109)


def test_custom_denylist_file_is_not_scanned(tmp_path):
    """Regression (#109): the denylist config in USE is exempt, whatever its path.

    ``_IGNORE_GLOBS`` used to name ``DEFAULT_DENYLIST_FILE`` literally, so a repo
    running ``--denylist-file custom/leakcheck-rules.txt`` got its own rules file
    enumerated and scanned as ordinary content. A denylist is a file of
    high-signal regexes, so the more useful its entries are as leak detectors the
    more certainly its own lines match one of them — and leakcheck gates a public
    push, where a false positive is most expensive.

    Counter-example property (#109 acceptance): this fails before the change and
    passes after. ``acme.corp`` matches itself both as the denylist rule it
    declares and under the built-in internal-hostname pattern.
    """
    rules_dir = tmp_path / "custom"
    rules_dir.mkdir()
    (rules_dir / "leakcheck-rules.txt").write_text("# internal hosts\nacme.corp\n")
    (tmp_path / "clean.md").write_text("nothing internal here\n")

    hits = scan(tmp_path, denylist_file="custom/leakcheck-rules.txt")
    assert hits == [], f"the denylist config in use must not be scanned; got {hits}"


def test_custom_denylist_file_exemption_normalizes_the_path(tmp_path):
    """(#109) The same file given three ways resolves to the same exemption.

    ``scan`` compares against a repo-relative POSIX string, so ``./x/y.txt``,
    ``x/y.txt`` and an absolute path under the root must all name it.
    """
    rules_dir = tmp_path / "custom"
    rules_dir.mkdir()
    denylist = rules_dir / "leakcheck-rules.txt"
    denylist.write_text("acme.corp\n")
    (tmp_path / "clean.md").write_text("nothing internal here\n")

    for spelling in (
        "custom/leakcheck-rules.txt",
        "./custom/leakcheck-rules.txt",
        str(denylist),
        denylist,
    ):
        assert scan(tmp_path, denylist_file=spelling) == [], f"spelling: {spelling!r}"


def test_default_denylist_file_is_still_exempt(tmp_path):
    """(#109) Deriving the exemption must not change the default case."""
    (tmp_path / leakcheck.DEFAULT_DENYLIST_FILE).write_text("acme.corp\n")
    (tmp_path / "clean.md").write_text("nothing internal here\n")

    assert scan(tmp_path) == []
    assert scan(tmp_path, denylist_file=leakcheck.DEFAULT_DENYLIST_FILE) == []


def test_denylist_file_none_exempts_nothing_extra(tmp_path):
    """(#109) With no denylist there is no denylist file to exempt.

    The scan still runs (the built-in patterns apply), and a file that merely
    happens to carry the default denylist NAME is ordinary content, because the
    caller asked for no denylist at all.
    """
    (tmp_path / leakcheck.DEFAULT_DENYLIST_FILE).write_text("acme.corp\n")
    (tmp_path / "notes.md").write_text("host: metrics.internal\n")

    files = {h.file for h in scan(tmp_path, denylist_file=None)}
    assert "notes.md" in files, "the scan must still run with no denylist"
    assert leakcheck.DEFAULT_DENYLIST_FILE in files, "nothing extra may be exempt"


def test_file_sharing_a_name_with_the_denylist_is_still_scanned(tmp_path):
    """(#109) The exemption is the specific path in use, not a loosened pattern.

    Second counter-example: a fix that widened ``_IGNORE_GLOBS`` to something like
    ``*leakcheck-rules.txt`` would pass ``test_custom_denylist_file_is_not_scanned``
    and fail here, silently un-scanning unrelated files.
    """
    rules_dir = tmp_path / "custom"
    rules_dir.mkdir()
    (rules_dir / "leakcheck-rules.txt").write_text("acme.corp\n")
    # Same basename, different directory — not the file that was passed.
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "leakcheck-rules.txt").write_text("host: build.internal\n")
    # Same directory, name sharing the passed file's suffix — also not it.
    (rules_dir / "old-leakcheck-rules.txt").write_text("host: legacy.internal\n")

    hits = scan(tmp_path, denylist_file="custom/leakcheck-rules.txt")
    assert {h.file for h in hits} == {
        "docs/leakcheck-rules.txt",
        "custom/old-leakcheck-rules.txt",
    }, f"only the denylist actually in use is exempt; got {hits}"


def test_fixed_self_exemptions_are_unchanged(tmp_path):
    """(#109) The three non-denylist exemptions stay exactly as they were."""
    for rel in (
        "pkg.egg-info/PKG-INFO",
        "src/zenodotus/leakcheck.py",
        "tests/test_leakcheck.py",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("built from ~/Code/private/thing\n")
    (tmp_path / "notes.md").write_text("path: ~/Code/also-here\n")

    assert {h.file for h in scan(tmp_path)} == {"notes.md"}
