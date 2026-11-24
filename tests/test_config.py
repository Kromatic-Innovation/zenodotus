"""Tests for configurable review (issue #134): ``.zenodotus.json``, scope by bump
class, reviewer lenses, prior rulings and the nit bar.

All offline: a recording stub provider stands in for the LLM, and the external
gate tools are disabled so the floor depends only on pure-Python checks.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from zenodotus import config, gates, panel
from zenodotus.cli import main

NOW = "2026-11-24T00:00:00Z"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class RecordingProvider:
    """Returns a fixed verdict and records the (reviewer_id, context) of each call."""

    def __init__(self, verdict=None):
        self._verdict = verdict or {"go": True, "rationale": "ready", "findings": []}
        self.calls: list[tuple[str, str]] = []
        self.requested_tools: list = []

    def review(self, reviewer_id, context, *, tools=None):
        self.calls.append((reviewer_id, context))
        return json.loads(json.dumps(self._verdict))


@pytest.fixture(autouse=True)
def no_external_tools(monkeypatch):
    monkeypatch.setattr(gates, "_which", lambda tool: None)
    monkeypatch.delenv("ZENODOTUS_MODEL", raising=False)


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                        "PATH": "/usr/bin:/bin:/usr/local/bin"})


def _repo(tmp_path, cfg=None, *, git=False):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "README.md").write_text("# Thing\nA genuinely useful public thing.\n")
    (d / "LICENSE").write_text("Apache License 2.0\n")
    (d / "CONTRIBUTING.md").write_text("# Contributing\n")
    if cfg is not None:
        (d / ".zenodotus.json").write_text(json.dumps(cfg))
    if git:
        _git(d, "init", "-q", "-b", "main")
        _git(d, "add", "-A")
        _git(d, "commit", "-q", "-m", "v0.1.0")
        _git(d, "tag", "v0.1.0")
        (d / "src.py").write_text("def added():\n    return 1\n")
        _git(d, "add", "-A")
        _git(d, "commit", "-q", "-m", "add src")
    return d


def _run(d, *extra, provider=None, capsys=None):
    provider = provider or RecordingProvider()
    code = main(["review", str(d), "--log", "", "--json", *extra], provider=provider, now=NOW)
    out = json.loads(capsys.readouterr().out) if capsys and code != 2 else None
    return code, out, provider


def _err(capsys):
    return capsys.readouterr().err


# --- precedence -------------------------------------------------------------- #


def test_defaults_with_no_config_file(tmp_path, capsys):
    code, out, prov = _run(_repo(tmp_path), capsys=capsys)
    assert code == 0
    s = out["settings"]
    assert out["config_file"] is None
    assert out["bump_class"] == "none"
    assert s["scope"] == {"value": "full", "source": "no-prior-tag"}
    assert s["personas"] == {"value": config.DEFAULT_PERSONAS, "source": "default"}
    assert s["prior_rulings"] == {"value": "on", "source": "default"}
    assert s["nit_bar"] == {"value": "strict", "source": "default"}
    assert s["cli.fail_on"] == {"value": "never", "source": "default"}
    assert s["cli.model"]["source"] == "default"
    # One reviewer per default lens, with the lens slug as the reviewer id.
    assert [c[0] for c in prov.calls] == config.DEFAULT_PERSONAS


def test_file_beats_default(tmp_path, capsys):
    d = _repo(tmp_path, {"nit_bar": "standard", "prior_rulings": "off",
                         "cli": {"fail_on": "blocker", "shadow": True}})
    _, out, _ = _run(d, capsys=capsys)
    s = out["settings"]
    assert out["config_file"] == str(d / ".zenodotus.json")
    assert s["nit_bar"] == {"value": "standard", "source": "file"}
    assert s["prior_rulings"] == {"value": "off", "source": "file"}
    assert s["cli.fail_on"] == {"value": "blocker", "source": "file"}
    assert s["cli.shadow"] == {"value": True, "source": "file"}
    assert out["shadow"] is True and out["fail_on"] == "blocker"


def test_flag_beats_file(tmp_path, capsys):
    d = _repo(tmp_path, {"nit_bar": "standard", "cli": {"fail_on": "blocker"}})
    _, out, _ = _run(d, "--nit-bar", "strict", "--fail-on", "never", capsys=capsys)
    assert out["settings"]["nit_bar"] == {"value": "strict", "source": "flag"}
    assert out["settings"]["cli.fail_on"] == {"value": "never", "source": "flag"}


def test_model_precedence_flag_env_file(tmp_path, monkeypatch):
    d = _repo(tmp_path, {"cli": {"model": "from-file"}})
    args = lambda *x: _ns(d, *x)
    assert config.resolve(args()).sources["cli.model"] == {"value": "from-file",
                                                           "source": "file"}
    monkeypatch.setenv("ZENODOTUS_MODEL", "from-env")
    assert config.resolve(args()).sources["cli.model"] == {"value": "from-env",
                                                           "source": "environment"}
    assert config.resolve(args("--model", "from-flag")).sources["cli.model"] == {
        "value": "from-flag", "source": "flag"}


def test_file_model_reaches_default_provider(tmp_path, monkeypatch):
    seen = {}

    class Fake(panel.AnthropicProvider):
        def review(self, reviewer_id, context, *, tools=None):
            seen["model"] = self.model
            return {"go": True, "rationale": "ok", "findings": []}

    monkeypatch.setattr(panel, "AnthropicProvider", Fake)
    d = _repo(tmp_path, {"cli": {"model": "model-from-file"}})
    assert main(["review", str(d), "--log", ""], now=NOW) == 0
    assert seen["model"] == "model-from-file"


def test_no_model_anywhere_still_exits_2(tmp_path, capsys):
    d = _repo(tmp_path)
    assert main(["review", str(d), "--log", ""], now=NOW) == 2
    assert "cli.model" in capsys.readouterr().err


def _ns(d, *extra):
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("path")
    for flag in ("--model", "--config", "--prior-tag", "--version", "--bump-class", "--scope",
                 "--personas", "--prior-rulings", "--prior-findings", "--nit-bar",
                 "--fail-on", "--reviewer-tools"):
        p.add_argument(flag, default=None)
    p.add_argument("--reviewers", type=int, default=None)
    p.add_argument("--no-config", action="store_true")
    for flag in ("--shadow", "--include-optional"):
        p.add_argument(flag, action="store_true", default=None)
    return p.parse_args([str(d), *extra])


# --- --config / --no-config --------------------------------------------------- #


def test_no_config_ignores_the_file(tmp_path, capsys):
    d = _repo(tmp_path, {"nit_bar": "standard"})
    _, out, _ = _run(d, "--no-config", capsys=capsys)
    assert out["config_file"] is None
    assert out["settings"]["nit_bar"] == {"value": "strict", "source": "default"}


def test_no_config_ignores_even_an_invalid_file(tmp_path, capsys):
    d = _repo(tmp_path, {"bogus": 1})
    code, _, _ = _run(d, "--no-config", capsys=capsys)
    assert code == 0


def test_config_flag_points_at_another_file(tmp_path, capsys):
    d = _repo(tmp_path, {"nit_bar": "strict"})
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"nit_bar": "standard"}))
    _, out, _ = _run(d, "--config", str(other), capsys=capsys)
    assert out["config_file"] == str(other)
    assert out["settings"]["nit_bar"]["value"] == "standard"


def test_config_flag_missing_file_exits_2(tmp_path, capsys):
    code, _, _ = _run(_repo(tmp_path), "--config", str(tmp_path / "nope.json"))
    assert code == 2
    assert "no such file" in _err(capsys)


# --- validation: exit 2 naming the dotted key ---------------------------------- #


@pytest.mark.parametrize("cfg, key", [
    ({"bogus": 1}, "'bogus'"),
    ({"cli": {"bogus": 1}}, "'cli.bogus'"),
    ({"scope": {"patch": "partial"}}, "'scope.patch'"),
    ({"scope": {"none": "full"}}, "'scope.none'"),
    ({"personas": ["no-such-lens"]}, "'personas'"),
    ({"personas": {"tiny": ["drive-by-installer"]}}, "'personas.tiny'"),
    ({"personas": {"patch": []}}, "'personas.patch'"),
    ({"prior_rulings": "yes"}, "'prior_rulings'"),
    ({"nit_bar": "lax"}, "'nit_bar'"),
    ({"cli": {"reviewers": 0}}, "'cli.reviewers'"),
    ({"cli": {"reviewers": True}}, "'cli.reviewers'"),
    ({"cli": {"fail_on": "always"}}, "'cli.fail_on'"),
    ({"cli": {"shadow": "yes"}}, "'cli.shadow'"),
    ({"cli": {"reviewer_tools": "recall"}}, "'cli.reviewer_tools'"),
    ({"cli": {"model": ""}}, "'cli.model'"),
    ({"cli": {"lenses": [{"id": "x", "focus": "f", "extra": 1}]}}, "'cli.lenses[0].extra'"),
    ({"cli": {"lenses": [{"id": "drive-by-installer", "focus": "f"}]}}, "'cli.lenses[0].id'"),
    # The shared `personas` key may not name a custom lens: the skill would
    # reject a slug it has no persona card for.
    ({"personas": ["mine"], "cli": {"lenses": [{"id": "mine", "focus": "f"}]}}, "'personas'"),
])
def test_invalid_key_or_value_exits_2_naming_the_key(tmp_path, capsys, cfg, key):
    code, _, _ = _run(_repo(tmp_path, cfg))
    assert code == 2
    assert key in _err(capsys)


def test_duplicate_key_exits_2(tmp_path, capsys):
    d = _repo(tmp_path)
    (d / ".zenodotus.json").write_text('{"nit_bar": "strict", "nit_bar": "standard"}')
    code, _, _ = _run(d)
    assert code == 2
    assert "'nit_bar' appears twice" in _err(capsys)


def test_malformed_json_exits_2(tmp_path, capsys):
    d = _repo(tmp_path)
    (d / ".zenodotus.json").write_text("{not json")
    assert _run(d)[0] == 2
    assert "not valid JSON" in _err(capsys)


def test_config_error_runs_nothing(tmp_path):
    prov = RecordingProvider()
    _run(_repo(tmp_path, {"bogus": 1}), provider=prov)
    assert prov.calls == []


def test_skill_only_keys_are_accepted_and_ignored(tmp_path, capsys):
    d = _repo(tmp_path, {"disposition": {"anything": "goes"}, "trivial_fix_max_lines": "x",
                         "rerun": {"scope": "whatever"}})
    code, out, _ = _run(d, capsys=capsys)
    assert code == 0
    assert "disposition" not in out["settings"]


def test_cross_tool_fixture_loads_cleanly(tmp_path, capsys):
    """The skill's own zenodotus.sample.json, plus a cli block, loads in the package.

    tests/fixtures/skill-zenodotus.sample.json is a byte copy of
    code-workspace-config's .claude/skills/zenodotus/zenodotus.sample.json on
    develop (2026-11-24). Re-copy it when the skill's schema changes.
    """
    sample = json.loads((FIXTURES / "skill-zenodotus.sample.json").read_text())
    assert sample["cli"] == {}  # the skill ships an empty cli block
    sample["cli"] = {
        "fail_on": "blocker", "include_optional": False,
        "reviewer_tools": [], "shadow": False, "model": "some-model",
        "lenses": [{"id": "api-auditor", "focus": "Judge the public API surface."}],
        "personas": {"major": ["drive-by-installer", "api-auditor"]},
    }
    d = _repo(tmp_path, sample)
    code, out, _ = _run(d, capsys=capsys)
    assert code == 0
    assert out["settings"]["cli.fail_on"]["value"] == "blocker"
    assert out["settings"]["scope"]["source"] == "no-prior-tag"


# --- bump class and scope ------------------------------------------------------ #


@pytest.mark.parametrize("prior, version, cls", [
    ("v0.3.0", "0.3.1", "patch"),
    ("v0.3.9", "0.4.0", "minor"),
    ("v0.3.0", "1.0.0", "major"),
    ("0.3.0", "v0.10.0", "minor"),
])
def test_bump_class_derivation(prior, version, cls):
    assert config.derive_bump_class(prior, version) == cls


@pytest.mark.parametrize("prior, version", [("v0.3.0", "0.3.0"), ("v0.3.0", "0.2.9"),
                                            ("v0.3", "0.4.0"), ("v0.3.0", "next")])
def test_bump_class_derivation_refuses_non_increasing_or_malformed(prior, version):
    with pytest.raises(config.ConfigError):
        config.derive_bump_class(prior, version)


def test_derived_bump_class_selects_scope(tmp_path, capsys):
    d = _repo(tmp_path, git=True)
    _, out, _ = _run(d, "--prior-tag", "v0.1.0", "--version", "0.1.1", capsys=capsys)
    assert out["bump_class"] == "patch"
    assert out["settings"]["scope"] == {"value": "diff", "source": "default"}
    _, out, _ = _run(d, "--prior-tag", "v0.1.0", "--version", "1.0.0", capsys=capsys)
    assert out["bump_class"] == "major"
    assert out["settings"]["scope"] == {"value": "full", "source": "default"}


def test_bump_class_flag_beats_derivation(tmp_path, capsys):
    d = _repo(tmp_path, git=True)
    _, out, _ = _run(d, "--prior-tag", "v0.1.0", "--version", "0.1.1", "--bump-class", "major",
                     capsys=capsys)
    assert out["bump_class"] == "major"


def test_file_scope_per_class(tmp_path, capsys):
    d = _repo(tmp_path, {"scope": {"patch": "full"}}, git=True)
    _, out, _ = _run(d, "--prior-tag", "v0.1.0", "--bump-class", "patch", capsys=capsys)
    assert out["settings"]["scope"] == {"value": "full", "source": "file"}


def test_none_forces_full_scope_even_when_file_says_diff(tmp_path, capsys):
    d = _repo(tmp_path, {"scope": {"patch": "diff", "minor": "diff", "major": "diff"}})
    _, out, _ = _run(d, capsys=capsys)
    assert out["bump_class"] == "none"
    assert out["settings"]["scope"] == {"value": "full", "source": "no-prior-tag"}


def test_diff_flag_without_prior_tag_exits_2(tmp_path, capsys):
    assert _run(_repo(tmp_path), "--scope", "diff")[0] == 2
    assert "prior tag" in _err(capsys)


def test_bump_class_without_prior_tag_exits_2(tmp_path, capsys):
    assert _run(_repo(tmp_path), "--bump-class", "patch")[0] == 2


def test_prior_tag_without_class_or_version_exits_2(tmp_path, capsys):
    assert _run(_repo(tmp_path, git=True), "--prior-tag", "v0.1.0")[0] == 2
    assert "--bump-class" in _err(capsys)


def test_unresolvable_prior_tag_in_diff_scope_exits_2(tmp_path, capsys, monkeypatch):
    from zenodotus import fileset
    monkeypatch.setattr(fileset, "_which", lambda tool: "/usr/bin/git")
    d = _repo(tmp_path, git=True)
    assert _run(d, "--prior-tag", "v9.9.9", "--bump-class", "patch")[0] == 2
    assert "does not resolve" in _err(capsys)


def test_diff_scope_sends_changed_files_and_diff(tmp_path, capsys):
    d = _repo(tmp_path, git=True)
    _, out, prov = _run(d, "--prior-tag", "v0.1.0", "--bump-class", "minor", capsys=capsys)
    assert out["settings"]["scope"]["value"] == "diff"
    ctx = prov.calls[0][1]
    assert "Review scope: diff" in ctx
    assert "## Changed files (git diff v0.1.0..HEAD)\n- src.py" in ctx
    assert "+def added():" in ctx
    assert "## README.md" in ctx  # the tree stays in for context


def test_full_scope_sends_no_diff(tmp_path, capsys):
    d = _repo(tmp_path, git=True)
    _, _, prov = _run(d, "--prior-tag", "v0.1.0", "--bump-class", "minor", "--scope", "full",
                      capsys=capsys)
    ctx = prov.calls[0][1]
    assert "Review scope: full" in ctx
    assert "Release diff" not in ctx


# --- in_diff never blocks --------------------------------------------------------- #

_OUT_OF_DIFF_BLOCKER = {
    "go": False, "rationale": "old README problem",
    "findings": [{"finding": "README is confusing", "category": "coherence",
                  "severity": "blocker", "rationale": "unchanged copy", "in_diff": False,
                  "repeat": False}],
}


def test_out_of_diff_blocker_never_blocks_even_with_fail_on_blocker(tmp_path, capsys):
    d = _repo(tmp_path, git=True)
    code, out, _ = _run(d, "--prior-tag", "v0.1.0", "--bump-class", "patch",
                        "--fail-on", "blocker",
                        provider=RecordingProvider(_OUT_OF_DIFF_BLOCKER), capsys=capsys)
    assert code == 0
    assert out["verdict"] == "warn"
    f = out["panel"]["verdicts"][0]["findings"][0]
    assert f["in_diff"] is False and f["repeat"] is False


def test_in_diff_blocker_still_blocks(tmp_path, capsys):
    v = json.loads(json.dumps(_OUT_OF_DIFF_BLOCKER))
    v["findings"][0]["in_diff"] = True
    d = _repo(tmp_path, git=True)
    code, out, _ = _run(d, "--prior-tag", "v0.1.0", "--bump-class", "patch",
                        "--fail-on", "blocker", provider=RecordingProvider(v), capsys=capsys)
    assert code == 1
    assert out["verdict"] == "block"


def test_full_scope_forces_in_diff_true(tmp_path, capsys):
    # In full scope the whole tree is under review, so a reviewer cannot
    # dodge a block by labelling a finding out of diff.
    code, out, _ = _run(_repo(tmp_path), "--fail-on", "blocker",
                        provider=RecordingProvider(_OUT_OF_DIFF_BLOCKER), capsys=capsys)
    assert code == 1
    assert out["panel"]["verdicts"][0]["findings"][0]["in_diff"] is True


def test_bare_no_go_still_blocks():
    v = panel.ReviewerVerdict(reviewer="r", go=False, findings=[], rationale="no")
    assert panel.any_blocker_no_go([v]) is False


# --- lenses ------------------------------------------------------------------------ #


def test_builtin_lens_slugs_match_the_skill():
    assert set(config.BUILTIN_LENSES) == {
        "drive-by-installer", "production-evaluator", "maintainers-maintainer",
        "drive-by-contributor"}


def test_lens_focus_reaches_each_reviewer_and_only_its_own(tmp_path, capsys):
    _, _, prov = _run(_repo(tmp_path), "--personas", "drive-by-installer,drive-by-contributor",
                      capsys=capsys)
    assert [c[0] for c in prov.calls] == ["drive-by-installer", "drive-by-contributor"]
    first, second = prov.calls[0][1], prov.calls[1][1]
    assert config.BUILTIN_LENSES["drive-by-installer"] in first
    assert config.BUILTIN_LENSES["drive-by-contributor"] not in first
    assert config.BUILTIN_LENSES["drive-by-contributor"] in second


def test_custom_lens_via_cli_lenses_and_cli_personas(tmp_path, capsys):
    d = _repo(tmp_path, {
        "personas": ["drive-by-installer"],
        "cli": {"lenses": [{"id": "api-auditor", "focus": "Audit the public API."}],
                "personas": ["api-auditor", "production-evaluator"]}})
    _, out, prov = _run(d, capsys=capsys)
    assert [c[0] for c in prov.calls] == ["api-auditor", "production-evaluator"]
    assert "Audit the public API." in prov.calls[0][1]
    assert out["settings"]["personas"] == {"value": ["api-auditor", "production-evaluator"],
                                           "source": "file"}


def test_personas_per_class_object(tmp_path, capsys):
    d = _repo(tmp_path, {"personas": {"none": ["drive-by-contributor"],
                                      "patch": ["drive-by-installer"]}})
    _, _, prov = _run(d, capsys=capsys)
    assert [c[0] for c in prov.calls] == ["drive-by-contributor"]


def test_personas_object_missing_class_uses_default(tmp_path, capsys):
    d = _repo(tmp_path, {"personas": {"patch": ["drive-by-installer"]}})
    _, out, _ = _run(d, capsys=capsys)
    assert out["settings"]["personas"]["source"] == "default"


def test_cli_reviewers_overrides_personas_with_generic_reviewers(tmp_path, capsys):
    d = _repo(tmp_path, {"personas": ["drive-by-installer"], "cli": {"reviewers": 2}})
    _, out, prov = _run(d, capsys=capsys)
    assert [c[0] for c in prov.calls] == ["reviewer-1", "reviewer-2"]
    assert out["settings"]["cli.reviewers"] == {"value": 2, "source": "file"}


def test_personas_flag_beats_file_reviewers(tmp_path, capsys):
    d = _repo(tmp_path, {"cli": {"reviewers": 2}})
    _, _, prov = _run(d, "--personas", "production-evaluator", capsys=capsys)
    assert [c[0] for c in prov.calls] == ["production-evaluator"]


def test_unknown_persona_flag_exits_2(tmp_path, capsys):
    assert _run(_repo(tmp_path), "--personas", "nobody")[0] == 2
    assert "unknown lens 'nobody'" in _err(capsys)


# --- prior rulings ------------------------------------------------------------------ #

_PRIOR = {"version": 1, "findings": [
    {"finding": "README install section is vague", "ruling": "dismissed"},
    {"finding": "No changelog link", "ruling": "filed", "ref": "#12"},
]}

_REPEAT_BLOCKER = {
    "go": False, "rationale": "again",
    "findings": [{"finding": "README install section is vague", "category": "doc-quality",
                  "severity": "blocker", "rationale": "still vague", "in_diff": True,
                  "repeat": True}],
}


def _prior_file(tmp_path, doc=_PRIOR):
    p = tmp_path / "prior.json"
    p.write_text(json.dumps(doc))
    return str(p)


def test_prior_findings_reach_reviewers_and_repeat_never_blocks(tmp_path, capsys):
    code, out, prov = _run(_repo(tmp_path), "--prior-findings", _prior_file(tmp_path),
                           "--fail-on", "blocker", provider=RecordingProvider(_REPEAT_BLOCKER),
                           capsys=capsys)
    ctx = prov.calls[0][1]
    assert "- [dismissed] README install section is vague" in ctx
    assert "- [filed (#12)] No changelog link" in ctx
    assert code == 0 and out["verdict"] == "warn"
    assert out["panel"]["verdicts"][0]["findings"][0]["repeat"] is True
    assert out["settings"]["prior_findings"]["source"] == "flag"


def test_prior_rulings_off_ignores_the_file(tmp_path, capsys):
    code, out, prov = _run(_repo(tmp_path), "--prior-findings", _prior_file(tmp_path),
                           "--prior-rulings", "off", "--fail-on", "blocker",
                           provider=RecordingProvider(_REPEAT_BLOCKER), capsys=capsys)
    assert "Prior rulings" not in prov.calls[0][1]
    # Without prior rulings in play a reviewer's `repeat` claim is not honoured.
    assert code == 1
    assert out["panel"]["verdicts"][0]["findings"][0]["repeat"] is False


@pytest.mark.parametrize("doc", [
    [],
    {"findings": [{"finding": "x", "ruling": "ignored"}]},
    {"findings": [{"finding": "x", "ruling": "filed"}]},
    {"findings": [{"finding": "", "ruling": "fixed"}]},
    {"findings": [{"finding": "x", "ruling": "fixed", "extra": 1}]},
    {"version": 2, "findings": []},
])
def test_invalid_prior_findings_exit_2(tmp_path, capsys, doc):
    assert _run(_repo(tmp_path), "--prior-findings", _prior_file(tmp_path, doc))[0] == 2


# --- nit bar ------------------------------------------------------------------------ #


def test_nit_bar_strict_adds_the_bar_standard_does_not(tmp_path, capsys):
    _, _, strict = _run(_repo(tmp_path), "--nit-bar", "strict", capsys=capsys)
    assert panel.STRICT_NIT_BAR in strict.calls[0][1]
    d2 = tmp_path / "b"
    d2.mkdir()
    _, _, standard = _run(_repo(d2), "--nit-bar", "standard", capsys=capsys)
    assert panel.STRICT_NIT_BAR not in standard.calls[0][1]


def test_library_defaults_send_todays_context_unchanged(tmp_path):
    """panel.review() keeps today's defaults: no brief, so cassettes still replay."""
    d = _repo(tmp_path)
    prov = RecordingProvider()
    panel.review(str(d), n_reviewers=1, provider=prov)
    assert prov.calls[0][1] == panel.gather_context(str(d))
    assert panel.reviewer_brief() == ""


# --- --json shape ---------------------------------------------------------------------- #


def test_json_records_every_setting_with_a_source(tmp_path, capsys):
    _, out, _ = _run(_repo(tmp_path), capsys=capsys)
    for key in ("scope", "personas", "prior_rulings", "nit_bar", "cli.reviewers",
                "cli.fail_on", "cli.include_optional", "cli.reviewer_tools", "cli.shadow",
                "cli.model", "cli.lenses", "prior_findings"):
        entry = out["settings"][key]
        assert set(entry) == {"value", "source"}
        assert entry["source"] in ("flag", "environment", "file", "default", "no-prior-tag")


# --- review follow-ups (PR #136) ------------------------------------------------------ #


def test_negative_flags_override_a_true_file_setting(tmp_path, capsys):
    d = _repo(tmp_path, {"cli": {"shadow": True, "include_optional": True}})
    _, out, _ = _run(d, "--no-shadow", "--no-include-optional", capsys=capsys)
    assert out["settings"]["cli.shadow"] == {"value": False, "source": "flag"}
    assert out["settings"]["cli.include_optional"] == {"value": False, "source": "flag"}
    assert out["shadow"] is False


def test_git_failure_in_diff_scope_exits_2_without_model_hint(tmp_path, capsys, monkeypatch):
    from zenodotus import fileset

    def boom(root, base):
        raise fileset.RefError("git diff v0.1.0..HEAD failed: shallow clone")

    monkeypatch.setattr(fileset, "changed_files", boom)
    d = _repo(tmp_path, git=True)
    assert _run(d, "--prior-tag", "v0.1.0", "--bump-class", "patch")[0] == 2
    err = _err(capsys)
    assert "shallow clone" in err
    assert "ZENODOTUS_MODEL" not in err
