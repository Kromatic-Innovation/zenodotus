"""Deterministic pre-gates — compose existing OSS-readiness tools.

Each gate wraps an external, permissively-licensed tool (or a pure-Python file
check) and returns a normalized :class:`GateResult`. The panel only runs after
the deterministic floor passes.

Wired gates:
  - license_present   -> file check + ``licensee`` (if installed)
  - community_files   -> README / CONTRIBUTING / CODE_OF_CONDUCT / SECURITY presence
  - no_secrets        -> Gitleaks
  - packaging_ok      -> ecosystem-aware: pyroma (Python) / package.json + ``npm pack`` (npm)
  - security_posture  -> OpenSSF Scorecard (optional; off by default)

External tools are invoked as subprocesses and are OPTIONAL: when a tool is not
installed the gate degrades gracefully — it reports ``skipped=True`` rather than
crashing. See docs/CONCEPT.md for the exact tools + versions wired.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Files that satisfy each community-health slot (case-insensitive stem match).
_LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING")
_COMMUNITY_SLOTS: dict[str, tuple[str, ...]] = {
    "README": ("README",),
    "CONTRIBUTING": ("CONTRIBUTING",),
    "CODE_OF_CONDUCT": ("CODE_OF_CONDUCT",),
    "SECURITY": ("SECURITY",),
}
# A repo may pass community_files while still missing the "recommended" slots.
_COMMUNITY_REQUIRED = ("README", "CONTRIBUTING")


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    skipped: bool = False  # tool absent / not applicable — surfaced, does not fail the floor
    tool: str = ""  # the external tool the gate composed, if any
    data: dict = field(default_factory=dict)  # structured extras for --json consumers


# --- injectable seams (monkeypatched in tests so gates run tool-free) -------- #

def _which(tool: str) -> str | None:
    return shutil.which(tool)


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _skipped(name: str, tool: str, why: str) -> GateResult:
    return GateResult(name=name, passed=False, skipped=True, tool=tool,
                      detail=f"{tool} not available — gate skipped ({why})")


# --- individual gates -------------------------------------------------------- #

def _find(root: Path, stems: tuple[str, ...]) -> Path | None:
    """First top-level file whose name/stem matches (case-insensitive), any extension.

    Matches ``LICENSE`` (no extension), ``LICENSE.md``, ``CODE_OF_CONDUCT.rst``.
    Hyphen and underscore are treated as equivalent so ``CODE-OF-CONDUCT`` matches.
    """
    def norm(s: str) -> str:
        return s.upper().replace("-", "_")

    wanted = {norm(s) for s in stems}
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        if norm(entry.stem) in wanted or norm(entry.name) in wanted:
            return entry
    return None


def license_present(path: str) -> GateResult:
    """A recognizable license file exists (and, if ``licensee`` is installed, is identifiable)."""
    root = Path(path)
    lic = _find(root, _LICENSE_NAMES)
    if lic is None:
        return GateResult("license_present", False, "no LICENSE/LICENCE/COPYING file found")

    detail = f"found {lic.name}"
    data: dict = {"file": lic.name}
    if _which("licensee"):
        proc = _run(["licensee", "detect", "--json", str(root)])
        if proc.returncode == 0 and proc.stdout.strip():
            detail = f"found {lic.name}; licensee identified a license"
            data["licensee"] = "identified"
        else:
            data["licensee"] = "inconclusive"
    return GateResult("license_present", True, detail, tool="licensee", data=data)


def community_files(path: str) -> GateResult:
    """README + CONTRIBUTING present (required); CoC + SECURITY reported as recommended."""
    root = Path(path)
    present = {slot: _find(root, stems) for slot, stems in _COMMUNITY_SLOTS.items()}
    have = {slot: (p is not None) for slot, p in present.items()}
    missing_required = [s for s in _COMMUNITY_REQUIRED if not have[s]]
    missing_recommended = [s for s, ok in have.items()
                           if not ok and s not in _COMMUNITY_REQUIRED]

    passed = not missing_required
    parts = [f"{'ok' if ok else 'missing'}:{slot}" for slot, ok in have.items()]
    detail = ", ".join(parts)
    if missing_recommended and passed:
        detail += f" (recommended missing: {', '.join(missing_recommended)})"
    return GateResult("community_files", passed, detail,
                      data={"present": have, "missing_required": missing_required})


def no_secrets(path: str) -> GateResult:
    """No leaked secrets, via Gitleaks. Degrades to skipped if gitleaks is absent."""
    if not _which("gitleaks"):
        return _skipped("no_secrets", "gitleaks", "install from github.com/gitleaks/gitleaks")
    proc = _run(["gitleaks", "detect", "--no-git", "--source", str(path),
                 "--redact", "--exit-code", "1"])
    # gitleaks exit codes: 0 = no leaks, 1 = leaks found, >1 = error.
    if proc.returncode == 0:
        return GateResult("no_secrets", True, "gitleaks: no leaks detected", tool="gitleaks")
    if proc.returncode == 1:
        return GateResult("no_secrets", False, "gitleaks: leaked secrets detected",
                          tool="gitleaks", data={"exit_code": 1})
    return GateResult("no_secrets", False,
                      f"gitleaks errored (exit {proc.returncode}): {proc.stderr.strip()[:200]}",
                      tool="gitleaks", data={"exit_code": proc.returncode})


# Packaging manifests we can gate, checked in order. The first match wins.
_PACKAGING_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("pyproject.toml", "setup.py", "setup.cfg")),
    ("npm", ("package.json",)),
)
# Ecosystems we recognize but don't gate yet — used only to make the skip legible
# instead of running a Python-only tool against them and hard-failing (#41).
_UNSUPPORTED_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("go", ("go.mod",)),
    ("rust", ("Cargo.toml",)),
    ("java-maven", ("pom.xml",)),
    ("java-gradle", ("build.gradle", "build.gradle.kts")),
    ("ruby", ("Gemfile",)),
    ("php", ("composer.json",)),
)
# package.json fields expected before an npm package can be meaningfully published.
_NPM_REQUIRED_FIELDS = ("name", "version")
_NPM_RECOMMENDED_FIELDS = ("description", "license", "repository")


def _detect_ecosystem(root: Path) -> str:
    """Classify a repo's packaging ecosystem from its manifest file(s).

    Returns a gateable ecosystem (``python`` / ``npm``), a recognized-but-
    ungated one (``go``, ``rust``, ...), or ``none`` when no manifest is found.
    """
    for eco, manifests in _PACKAGING_MANIFESTS:
        if any((root / m).is_file() for m in manifests):
            return eco
    for eco, manifests in _UNSUPPORTED_MANIFESTS:
        if any((root / m).is_file() for m in manifests):
            return eco
    return "none"


def packaging_ok(path: str) -> GateResult:
    """Packaging hygiene, ecosystem-aware (#41).

    Detects the repo's packaging ecosystem from its manifest and runs the
    matching check instead of always shelling out to ``pyroma`` (which only
    understands Python packaging and rated any non-Python repo 0/10, hard-failing
    the floor deterministically):

      - Python (``pyproject.toml`` / ``setup.py`` / ``setup.cfg``) -> pyroma
      - npm    (``package.json``)                                  -> field hygiene + ``npm pack --dry-run``
      - any other / no manifest                                    -> skipped (surfaced, does not fail the floor)
    """
    root = Path(path)
    ecosystem = _detect_ecosystem(root)
    if ecosystem == "python":
        return _packaging_ok_python(path)
    if ecosystem == "npm":
        return _packaging_ok_npm(root)
    why = ("no packaging manifest found" if ecosystem == "none"
           else f"{ecosystem} packaging not gated yet")
    return GateResult("packaging_ok", False, f"packaging gate skipped — {why}",
                      skipped=True, data={"ecosystem": ecosystem})


def _packaging_ok_python(path: str) -> GateResult:
    """PyPI packaging hygiene via pyroma. Degrades to skipped if pyroma is absent.

    (``twine check`` is deliberately not run: it needs a built ``dist/``, which
    a review of an arbitrary checkout does not have; pyroma works directly
    against the source tree and is the floor here.)
    """
    if not _which("pyroma"):
        return _skipped("packaging_ok", "pyroma", "pip install pyroma")
    proc = _run(["pyroma", "--min", "8", str(path)])
    passed = proc.returncode == 0
    tail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or [""]
    return GateResult("packaging_ok", passed,
                      f"pyroma (min rating 8/10): {'pass' if passed else 'fail'} — {tail[0][:160]}",
                      tool="pyroma", data={"exit_code": proc.returncode, "ecosystem": "python"})


def _packaging_ok_npm(root: Path) -> GateResult:
    """npm packaging hygiene: package.json field checks + optional ``npm pack --dry-run``.

    package.json parsing is pure-Python (always available); ``npm pack`` is only
    run when the ``npm`` binary is installed and its absence degrades that deeper
    step gracefully — matching the tool-absent contract of the other gates.
    """
    import json

    pkg_path = root / "package.json"
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return GateResult("packaging_ok", False,
                          f"package.json present but unreadable: {exc}",
                          tool="npm", data={"ecosystem": "npm"})
    if not isinstance(pkg, dict):
        return GateResult("packaging_ok", False, "package.json is not a JSON object",
                          tool="npm", data={"ecosystem": "npm"})

    # A package marked private is legitimately not an npm publish target — surface
    # it as skipped rather than failing hygiene it never intended to meet.
    if pkg.get("private") is True:
        return GateResult("packaging_ok", False,
                          'package.json "private": true — not an npm publish target; gate skipped',
                          skipped=True, tool="npm", data={"ecosystem": "npm", "private": True})

    missing_required = [f for f in _NPM_REQUIRED_FIELDS if not pkg.get(f)]
    missing_recommended = [f for f in _NPM_RECOMMENDED_FIELDS if not pkg.get(f)]
    data: dict = {"ecosystem": "npm", "missing_required": missing_required,
                  "missing_recommended": missing_recommended}
    if missing_required:
        return GateResult("packaging_ok", False,
                          f"package.json missing required field(s): {', '.join(missing_required)}",
                          tool="npm", data=data)

    detail = "package.json ok (name, version present)"
    if missing_recommended:
        detail += f"; recommended missing: {', '.join(missing_recommended)}"

    if _which("npm"):
        proc = _run(["npm", "pack", "--dry-run"], cwd=str(root))
        data["npm_pack_exit"] = proc.returncode
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or [""]
            return GateResult("packaging_ok", False,
                              f"npm pack --dry-run failed (exit {proc.returncode}): {tail[0][:160]}",
                              tool="npm", data=data)
        detail = f"npm pack --dry-run ok; {detail}"
    else:
        detail += " (npm not installed — pack dry-run skipped)"
    return GateResult("packaging_ok", True, detail, tool="npm", data=data)


def security_posture(path: str) -> GateResult:
    """OpenSSF Scorecard — optional/heavier, off unless explicitly included."""
    if not _which("scorecard"):
        return _skipped("security_posture", "scorecard", "OpenSSF Scorecard; optional")
    proc = _run(["scorecard", f"--local={path}", "--format=json"])
    passed = proc.returncode == 0
    return GateResult("security_posture", passed,
                      f"scorecard exit {proc.returncode}", tool="scorecard",
                      data={"exit_code": proc.returncode})


# --- aggregation ------------------------------------------------------------- #

# Ordered so cheap pure-Python checks run before subprocess tools.
_REQUIRED_GATES = (license_present, community_files, no_secrets, packaging_ok)
_OPTIONAL_GATES = (security_posture,)


def run_all(path: str, include_optional: bool = False) -> list[GateResult]:
    """Run every deterministic gate against ``path`` and return normalized results.

    A gate that raises is reported as a failed result rather than aborting the
    batch — the floor must never crash the pipeline.
    """
    gates = list(_REQUIRED_GATES) + (list(_OPTIONAL_GATES) if include_optional else [])
    results: list[GateResult] = []
    for gate in gates:
        try:
            results.append(gate(path))
        except Exception as exc:  # noqa: BLE001 — report, never crash the floor
            results.append(GateResult(gate.__name__, False,
                                      f"gate raised {type(exc).__name__}: {exc}"))
    return results


def floor_passed(results: list[GateResult]) -> bool:
    """The floor passes when no non-skipped gate failed.

    Skipped gates (absent optional tool) are surfaced but do not block — this is
    the graceful-degradation contract. Callers wanting strictness can inspect
    ``skipped`` themselves.
    """
    return all(r.passed for r in results if not r.skipped)
