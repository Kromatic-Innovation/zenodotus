"""Deterministic pre-gates — compose existing OSS-readiness tools (scaffold).

Each gate wraps an external, permissively-licensed tool and returns a normalized
GateResult. The panel only runs after every required gate passes.

Planned gates (see repo issues):
  - license_present   -> REUSE / licensee / GitHub Community Standards
  - community_files   -> README / CONTRIBUTING / CoC / SECURITY presence
  - no_secrets        -> Gitleaks
  - packaging_ok      -> pyroma + twine check
  - security_posture  -> OpenSSF Scorecard (optional)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


def run_all(path: str) -> list[GateResult]:
    raise NotImplementedError("deterministic gate composition — see repo issues")
