"""Effective review settings — CLI flags, ``ZENODOTUS_MODEL``, ``.zenodotus.json``, defaults.

One committed ``.zenodotus.json`` at the reviewed repo's root configures both
this package and the workspace release-gate skill. The shared keys (``scope``,
``personas``, ``prior_rulings``, ``nit_bar``) use the skill's names, values and
defaults exactly. Package-only settings live under one ``cli`` object, which the
skill accepts and ignores. The skill's own release-gate keys (``disposition``,
``trivial_fix_max_lines``, ``rerun``) are accepted here and ignored, so a shared
file never breaks the package.

Precedence, highest first: CLI flag, then ``ZENODOTUS_MODEL`` (for ``model``
only), then the file, then the built-in default. :func:`resolve` returns every
effective value together with its source — ``flag``, ``environment``, ``file``,
``default`` or ``no-prior-tag`` — which ``--json`` records under ``settings``,
in the same ``{key: {value, source}}`` shape the skill prints.

Any problem with the file, a flag value or the refs a setting needs raises
:class:`ConfigError`; the CLI turns that into exit 2 ("could not run").

Standard library only: the package stays dependency-free.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import fileset

CONFIG_FILENAME = ".zenodotus.json"
MODEL_ENV_VAR = "ZENODOTUS_MODEL"

BUMP_CLASSES = ("patch", "minor", "major", "none")
SCOPES = ("diff", "full")
ON_OFF = ("on", "off")
NIT_BARS = ("strict", "standard")
FAIL_ON_CHOICES = ("blocker", "never")

# The skill's defaults (operator ruling 2026-11-23): an unconfigured run gets
# diff-scoped review on patch and minor releases.
DEFAULT_SCOPE = {"patch": "diff", "minor": "diff", "major": "full"}
DEFAULT_PERSONAS = ["drive-by-installer", "production-evaluator", "maintainers-maintainer"]
DEFAULT_PRIOR_RULINGS = "on"
DEFAULT_NIT_BAR = "strict"
DEFAULT_FAIL_ON = "never"

# Built-in reviewer lenses, with the skill's persona slugs. A lens adds a focus
# to a reviewer's brief; it never adds internal context, and reviewers stay
# blind to each other.
BUILTIN_LENSES: dict[str, str] = {
    "drive-by-installer": (
        "You are a working engineer who found this project ten minutes ago and has "
        "five minutes to get it working. Judge the README's first screenful, the "
        "install command on a clean machine, and whether the quickstart runs as "
        "pasted. Flag undocumented system dependencies, required configuration that "
        "is not called out before the quickstart, and docs that describe a version "
        "other than the one being shipped."
    ),
    "production-evaluator": (
        "You are a staff engineer vetting this for production use; your name goes on "
        "the postmortem. Judge versioning and changelog honesty, dependency hygiene, "
        "whether the documented public API is a real, stable surface, error handling "
        "and operational behaviour, the security surface (network, subprocess, "
        "filesystem, secrets) and the maintenance signal."
    ),
    "maintainers-maintainer": (
        "You are a senior open-source maintainer reading a peer's release before "
        "they tag it. Judge whether the release tells one coherent story, whether "
        "public-API changes are called out, whether new surface has tests, whether "
        "the CHANGELOG describes the change you actually see, whether the version "
        "bump is honest, and whether the code keeps its own conventions."
    ),
    "drive-by-contributor": (
        "You hit a bug an hour ago and have thirty minutes to report or fix it. "
        "Judge the issue path, CONTRIBUTING.md, whether a clean checkout reaches "
        "passing tests using only the documented commands, where PRs go, and "
        "whether anything (a heavyweight CLA, exotic tooling) would stop a small fix."
    ),
}

SHARED_KEYS = ("scope", "personas", "prior_rulings", "nit_bar")
# The skill's release-gate keys (cwc#3724). Accepted and ignored here: the
# skill validates them, and the package has no use for them.
SKILL_ONLY_KEYS = ("disposition", "trivial_fix_max_lines", "rerun")
TOP_KEYS = SHARED_KEYS + SKILL_ONLY_KEYS + ("cli",)
CLI_KEYS = (
    "reviewers", "fail_on", "include_optional", "reviewer_tools", "shadow", "model",
    "lenses", "personas",
)
_LENS_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


class ConfigError(ValueError):
    """The configuration cannot be resolved. The CLI exits 2 ("could not run")."""


@dataclass
class Settings:
    """Every effective review setting, plus where each one came from."""

    bump_class: str
    config_file: str | None
    scope: str
    prior_tag: str | None
    # Generic-reviewer count when the panel is not lens-based (``cli.reviewers``
    # or ``--reviewers``), else None.
    reviewers: int | None
    # (lens id, focus) pairs when the panel is lens-based, else empty.
    lenses: list[tuple[str, str]]
    prior_rulings: str
    prior_findings: list[dict] | None
    nit_bar: str
    fail_on: str
    include_optional: bool
    reviewer_tools: list[str] | None
    shadow: bool
    model: str | None
    sources: dict[str, dict] = field(default_factory=dict)


# --- file loading ------------------------------------------------------------ #


def _no_dupes(pairs):
    seen: dict = {}
    for k, v in pairs:
        if k in seen:
            raise ConfigError(f"{CONFIG_FILENAME}: key '{k}' appears twice")
        seen[k] = v
    return seen


def load_file(path: str | Path) -> dict:
    """Parse and validate a config file. Returns the parsed object."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {p}: {exc.strerror or exc}") from exc
    try:
        cfg = json.loads(text, object_pairs_hook=_no_dupes)
    except ConfigError:
        raise
    except ValueError as exc:
        raise ConfigError(f"{CONFIG_FILENAME}: not valid JSON ({exc})") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"{CONFIG_FILENAME}: top level must be a JSON object")
    validate(cfg)
    return cfg


def _bad(msg: str) -> ConfigError:
    return ConfigError(f"{CONFIG_FILENAME}: {msg}")


def _check_lens_list(val, where: str, known: set[str]) -> None:
    if not isinstance(val, list) or not val:
        raise _bad(f"key '{where}' must be a non-empty list of lens slugs")
    for x in val:
        if not isinstance(x, str) or x not in known:
            raise _bad(f"key '{where}' has unknown lens {x!r} (known: {', '.join(sorted(known))})")
    if len(set(val)) != len(val):
        raise _bad(f"key '{where}' lists a lens twice")


def _check_personas(val, where: str, known: set[str]) -> None:
    if isinstance(val, dict):
        for k, v in val.items():
            if k not in BUMP_CLASSES:
                raise _bad(f"unknown key '{where}.{k}' (known: {', '.join(BUMP_CLASSES)})")
            _check_lens_list(v, f"{where}.{k}", known)
    else:
        _check_lens_list(val, where, known)


def validate(cfg: dict) -> None:
    """Validate every key the package owns; raise :class:`ConfigError` naming the key."""
    for k in cfg:
        if k not in TOP_KEYS:
            raise _bad(f"unknown key '{k}' (known: {', '.join(TOP_KEYS)})")

    if "scope" in cfg:
        s = cfg["scope"]
        if not isinstance(s, dict):
            raise _bad("key 'scope' must be an object keyed by patch, minor, major")
        for k, v in s.items():
            if k not in DEFAULT_SCOPE:
                raise _bad(f"unknown key 'scope.{k}' (known: patch, minor, major)")
            if v not in SCOPES:
                raise _bad(f"key 'scope.{k}' must be diff or full (got {v!r})")

    if "prior_rulings" in cfg and cfg["prior_rulings"] not in ON_OFF:
        raise _bad(f"key 'prior_rulings' must be on or off (got {cfg['prior_rulings']!r})")
    if "nit_bar" in cfg and cfg["nit_bar"] not in NIT_BARS:
        raise _bad(f"key 'nit_bar' must be strict or standard (got {cfg['nit_bar']!r})")

    cli = cfg.get("cli", {})
    if not isinstance(cli, dict):
        raise _bad("key 'cli' must be an object")
    for k in cli:
        if k not in CLI_KEYS:
            raise _bad(f"unknown key 'cli.{k}' (known: {', '.join(CLI_KEYS)})")

    custom: dict[str, str] = {}
    if "lenses" in cli:
        lenses = cli["lenses"]
        if not isinstance(lenses, list):
            raise _bad("key 'cli.lenses' must be a list of {id, focus} objects")
        for i, lens in enumerate(lenses):
            where = f"cli.lenses[{i}]"
            if not isinstance(lens, dict):
                raise _bad(f"key '{where}' must be an object with id and focus")
            for lk in lens:
                if lk not in ("id", "focus"):
                    raise _bad(f"unknown key '{where}.{lk}' (known: id, focus)")
            lid, focus = lens.get("id"), lens.get("focus")
            if not isinstance(lid, str) or not _LENS_ID.match(lid):
                raise _bad(f"key '{where}.id' must be a lowercase slug (got {lid!r})")
            if lid in BUILTIN_LENSES or lid in custom:
                raise _bad(f"key '{where}.id' {lid!r} is already defined")
            if not isinstance(focus, str) or not focus.strip():
                raise _bad(f"key '{where}.focus' must be a non-empty string")
            custom[lid] = focus

    builtin = set(BUILTIN_LENSES)
    if "personas" in cfg:
        _check_personas(cfg["personas"], "personas", builtin)
    if "personas" in cli:
        _check_personas(cli["personas"], "cli.personas", builtin | set(custom))

    if "reviewers" in cli:
        r = cli["reviewers"]
        if isinstance(r, bool) or not isinstance(r, int) or r < 1:
            raise _bad(f"key 'cli.reviewers' must be a positive integer (got {r!r})")
    if "fail_on" in cli and cli["fail_on"] not in FAIL_ON_CHOICES:
        raise _bad(f"key 'cli.fail_on' must be blocker or never (got {cli['fail_on']!r})")
    for k in ("include_optional", "shadow"):
        if k in cli and not isinstance(cli[k], bool):
            raise _bad(f"key 'cli.{k}' must be true or false (got {cli[k]!r})")
    if "reviewer_tools" in cli:
        t = cli["reviewer_tools"]
        if not isinstance(t, list) or not all(isinstance(x, str) and x.strip() for x in t):
            raise _bad("key 'cli.reviewer_tools' must be a list of tool names")
    if "model" in cli and (not isinstance(cli["model"], str) or not cli["model"].strip()):
        raise _bad("key 'cli.model' must be a non-empty model id")


def custom_lenses(cfg: dict) -> dict[str, str]:
    return {lens["id"]: lens["focus"] for lens in cfg.get("cli", {}).get("lenses", [])}


# --- bump class -------------------------------------------------------------- #


def _parse_semver(v: str, what: str) -> tuple[int, int, int]:
    m = _SEMVER.match(v.strip())
    if not m:
        raise ConfigError(f"{what} must be MAJOR.MINOR.PATCH (got {v!r})")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def derive_bump_class(prior_tag: str, version: str) -> str:
    """SemVer bump class of ``version`` against ``prior_tag`` (``patch|minor|major``).

    Matches the skill's preflight: the first differing component of
    MAJOR.MINOR.PATCH names the class. ``version`` must be greater than the
    prior tag's version.
    """
    pv = _parse_semver(prior_tag, "--prior-tag")
    tv = _parse_semver(version, "--version")
    if tv <= pv:
        raise ConfigError(
            f"--version {version} must be greater than --prior-tag {prior_tag}"
        )
    if tv[0] != pv[0]:
        return "major"
    if tv[1] != pv[1]:
        return "minor"
    return "patch"


def resolve_bump_class(
    *, bump_class: str | None, prior_tag: str | None, version: str | None
) -> str:
    """The run's bump class: ``none`` without a prior tag, else flagged or derived."""
    if not prior_tag:
        if bump_class and bump_class != "none":
            raise ConfigError(
                f"--bump-class {bump_class} needs --prior-tag; with no prior tag the "
                "class is none and the scope is always full"
            )
        return "none"
    if bump_class:
        if bump_class == "none":
            raise ConfigError("--bump-class none cannot be combined with --prior-tag")
        return bump_class
    if version:
        return derive_bump_class(prior_tag, version)
    raise ConfigError(
        "--prior-tag needs --bump-class, or --version to derive the bump class from"
    )


# --- prior findings ---------------------------------------------------------- #

RULINGS = ("fixed", "filed", "dismissed")
_PRIOR_FINDING_KEYS = ("finding", "ruling", "ref", "category", "severity")


def load_prior_findings(path: str | Path) -> list[dict]:
    """Load a prior-findings file (docs/PANEL_VERDICT_SPEC.md §5)."""
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read --prior-findings {p}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"--prior-findings {p}: not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        raise ConfigError(f"--prior-findings {p}: must be an object with a 'findings' list")
    if doc.get("version", 1) != 1:
        raise ConfigError(f"--prior-findings {p}: unsupported version {doc.get('version')!r}")
    out: list[dict] = []
    for i, f in enumerate(doc["findings"]):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            raise ConfigError(f"--prior-findings: '{where}' must be an object")
        for k in f:
            if k not in _PRIOR_FINDING_KEYS:
                raise ConfigError(
                    f"--prior-findings: unknown key '{where}.{k}' "
                    f"(known: {', '.join(_PRIOR_FINDING_KEYS)})"
                )
        if not isinstance(f.get("finding"), str) or not f["finding"].strip():
            raise ConfigError(f"--prior-findings: '{where}.finding' must be a non-empty string")
        if f.get("ruling") not in RULINGS:
            raise ConfigError(
                f"--prior-findings: '{where}.ruling' must be one of {', '.join(RULINGS)} "
                f"(got {f.get('ruling')!r})"
            )
        if f["ruling"] == "filed" and not (isinstance(f.get("ref"), str) and f["ref"].strip()):
            raise ConfigError(f"--prior-findings: '{where}.ref' is required for a filed ruling")
        out.append(dict(f))
    return out


# --- resolution -------------------------------------------------------------- #


def _split_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def resolve(args, *, environ=None) -> Settings:
    """Resolve the effective settings for one ``zenodotus review`` run.

    ``args`` is the parsed argparse namespace. A flag the user did not pass is
    ``None``. Raises :class:`ConfigError` on any invalid input.
    """
    env = os.environ if environ is None else environ
    src: dict[str, dict] = {}

    def put(key, value, source):
        src[key] = {"value": value, "source": source}
        return value

    # File.
    config_path: Path | None = None
    if not getattr(args, "no_config", False):
        explicit = getattr(args, "config", None)
        if explicit:
            config_path = Path(explicit)
            if not config_path.is_file():
                raise ConfigError(f"--config {explicit}: no such file")
        else:
            candidate = Path(args.path) / CONFIG_FILENAME
            config_path = candidate if candidate.is_file() else None
    cfg = load_file(config_path) if config_path else {}
    cli = cfg.get("cli", {})

    # Bump class and scope.
    prior_tag = getattr(args, "prior_tag", None) or None
    bump = resolve_bump_class(
        bump_class=getattr(args, "bump_class", None),
        prior_tag=prior_tag,
        version=getattr(args, "version", None),
    )
    flag_scope = getattr(args, "scope", None)
    if bump == "none":
        if flag_scope == "diff":
            raise ConfigError(
                "--scope diff needs a prior tag; with no prior tag the scope is always full"
            )
        scope = put("scope", "full", "no-prior-tag")
    elif flag_scope:
        scope = put("scope", flag_scope, "flag")
    elif bump in cfg.get("scope", {}):
        scope = put("scope", cfg["scope"][bump], "file")
    else:
        scope = put("scope", DEFAULT_SCOPE[bump], "default")
    if scope == "diff":
        try:
            fileset.verify_ref(args.path, prior_tag)
        except fileset.RefError as exc:
            raise ConfigError(str(exc)) from exc

    # Panel: generic reviewers or lenses.
    known = dict(BUILTIN_LENSES)
    known.update(custom_lenses(cfg))

    def per_class(val):
        if isinstance(val, dict):
            return val.get(bump)
        return val

    flag_reviewers = getattr(args, "reviewers", None)
    flag_personas = getattr(args, "personas", None)
    reviewers: int | None = None
    lens_ids: list[str] = []
    if flag_reviewers is not None:
        if flag_reviewers < 1:
            raise ConfigError(f"--reviewers must be a positive integer (got {flag_reviewers})")
        reviewers = put("cli.reviewers", flag_reviewers, "flag")
    elif flag_personas:
        lens_ids = _split_list(flag_personas)
        for x in lens_ids:
            if x not in known:
                raise ConfigError(
                    f"--personas has unknown lens {x!r} (known: {', '.join(sorted(known))})"
                )
        if not lens_ids or len(set(lens_ids)) != len(lens_ids):
            raise ConfigError("--personas must be a comma-separated list of distinct lens slugs")
        put("personas", lens_ids, "flag")
    elif "reviewers" in cli:
        reviewers = put("cli.reviewers", cli["reviewers"], "file")
    elif per_class(cli.get("personas")):
        lens_ids = put("personas", list(per_class(cli["personas"])), "file")
    elif per_class(cfg.get("personas")):
        lens_ids = put("personas", list(per_class(cfg["personas"])), "file")
    else:
        lens_ids = put("personas", list(DEFAULT_PERSONAS), "default")
    if reviewers is not None:
        put("personas", None, src["cli.reviewers"]["source"])
    else:
        put("cli.reviewers", None, src["personas"]["source"])
    lenses = [(lid, known[lid]) for lid in lens_ids]
    custom = custom_lenses(cfg)
    put("cli.lenses", [{"id": k, "focus": v} for k, v in custom.items()],
        "file" if custom else "default")

    # Prior rulings and nit bar.
    def shared(key, flag_value, default):
        if flag_value:
            return put(key, flag_value, "flag")
        if key in cfg:
            return put(key, cfg[key], "file")
        return put(key, default, "default")

    prior_rulings = shared("prior_rulings", getattr(args, "prior_rulings", None),
                           DEFAULT_PRIOR_RULINGS)
    nit_bar = shared("nit_bar", getattr(args, "nit_bar", None), DEFAULT_NIT_BAR)

    prior_findings = None
    pf_path = getattr(args, "prior_findings", None)
    if pf_path:
        loaded = load_prior_findings(pf_path)  # validated even when rulings are off
        if prior_rulings == "on":
            prior_findings = loaded
    put("prior_findings", pf_path if prior_findings is not None else None,
        "flag" if prior_findings is not None else "default")

    # Package-only cli.* settings.
    def cli_setting(key, flag_value, default):
        if flag_value is not None:
            return put(f"cli.{key}", flag_value, "flag")
        if key in cli:
            return put(f"cli.{key}", cli[key], "file")
        return put(f"cli.{key}", default, "default")

    fail_on = cli_setting("fail_on", getattr(args, "fail_on", None), DEFAULT_FAIL_ON)
    include_optional = cli_setting("include_optional", getattr(args, "include_optional", None),
                                   False)
    shadow = cli_setting("shadow", getattr(args, "shadow", None), False)
    flag_tools = getattr(args, "reviewer_tools", None)
    if isinstance(flag_tools, str):
        flag_tools = _split_list(flag_tools)
    reviewer_tools = cli_setting("reviewer_tools", flag_tools, None)

    flag_model = getattr(args, "model", None)
    env_model = env.get(MODEL_ENV_VAR) or None
    if flag_model:
        model = put("cli.model", flag_model, "flag")
    elif env_model:
        model = put("cli.model", env_model, "environment")
    elif "model" in cli:
        model = put("cli.model", cli["model"], "file")
    else:
        model = put("cli.model", None, "default")

    return Settings(
        bump_class=bump,
        config_file=str(config_path) if config_path else None,
        scope=scope,
        prior_tag=prior_tag,
        reviewers=reviewers,
        lenses=lenses,
        prior_rulings=prior_rulings,
        prior_findings=prior_findings,
        nit_bar=nit_bar,
        fail_on=fail_on,
        include_optional=include_optional,
        reviewer_tools=reviewer_tools,
        shadow=shadow,
        model=model,
        sources=src,
    )
