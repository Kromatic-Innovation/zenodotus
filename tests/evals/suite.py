"""The eval suite — the second prove-itself gate (docs/CONCEPT.md).

Real logged discoveries from the prove-itself run (issue #4) are distilled here
into a small corpus of fixtures + **expected panel verdicts** that the panel
passes reproducibly, fully offline (recorded cassettes — no API key, no network).

This module is the artifact the public-flip decision references (issue #5): the
flip to public is gated on ``run_suite()`` reporting every case OK. Run it with::

    python tests/evals/suite.py

Add a case to ``EVAL_CASES`` — with its fixture under ``fixtures/`` and a recorded
cassette under ``cassettes/`` — as new discovery themes are logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from zenodotus import panel
from zenodotus.cassette import CassetteProvider

EVALS_DIR = Path(__file__).resolve().parent
FIXTURES = EVALS_DIR / "fixtures"
CASSETTES = EVALS_DIR / "cassettes"

# Fixed timestamp for discovery-log stamping — the panel never reads the clock,
# so a constant keeps eval results byte-stable across runs.
_AT = "2026-01-01T00:00:00Z"


@dataclass(frozen=True)
class EvalCase:
    """One eval: a fixture repo + the panel verdict we expect it to reproduce."""

    name: str
    fixture: str  # directory name under fixtures/
    cassette: str  # file name under cassettes/
    expect_go: bool  # expected consensus verdict (back-compat boolean)
    expect_verdict: str  # expected three-state projection: "pass" | "warn" | "block"
    expect_categories: tuple[str, ...] = ()  # sorted discovery categories expected
    expect_blocker: bool = False
    derived_from: str = ""  # the real logged-discovery theme this case pins down


# Each case is distilled from a real logged discovery theme (docs/CONCEPT.md
# "Discovery log"; issues #4 / #30).
EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        name="mediocre-readme",
        fixture="mediocre-readme",
        cassette="mediocre-readme.json",
        expect_go=False,
        expect_verdict="block",
        expect_categories=("naming", "usefulness"),
        expect_blocker=True,
        derived_from=(
            "genuine panel-only findings: a README promising usage it does not "
            "ship (usefulness blocker) + a naming nit — the panel correctly blocks."
        ),
    ),
    EvalCase(
        name="warn-advisory",
        fixture="warn-advisory",
        cassette="warn-advisory.json",
        expect_go=True,
        expect_verdict="warn",
        expect_categories=("doc-quality", "naming"),
        expect_blocker=False,
        derived_from=(
            "the middle state (#31): a genuinely ship-able library with only "
            "advisory major/minor findings (a documented-but-incomplete error "
            "contract + a naming nit) and no blocker. Every reviewer says go, so "
            "the panel neither blocks nor passes silently — it WARNs. Pins the "
            "three-state model's warn pole (warnings never block, exit 0)."
        ),
    ),
    EvalCase(
        name="clean-complete",
        fixture="clean-complete",
        cassette="clean-complete.json",
        expect_go=True,
        expect_verdict="pass",
        expect_categories=(),
        expect_blocker=False,
        derived_from=(
            "the tickle-stick / athenaeum false-blocker themes (#30): a complete "
            ">8k-char README + a present LICENSE that the OLD gather_context "
            "false-blocked (truncation reading as 'unfinished'; omitted LICENSE "
            "reading as license uncertainty). With the fix the panel sees clean "
            "context and passes it — no false blocker reproduces."
        ),
    ),
)


@dataclass
class EvalResult:
    name: str
    ok: bool
    detail: str
    consensus_go: bool
    verdict: str = "pass"  # three-state projection: pass | warn | block
    categories: list[str] = field(default_factory=list)
    has_blocker: bool = False


def run_case(case: EvalCase) -> EvalResult:
    """Run one eval offline against its recorded cassette and check expectations."""
    provider = CassetteProvider(CASSETTES / case.cassette)  # replay mode; no network
    review = panel.review(
        str(FIXTURES / case.fixture),
        n_reviewers=3,
        provider=provider,
        at=_AT,
        repo_name=case.name,
    )
    categories = sorted(d.category for d in review.discoveries)
    has_blocker = any(d.severity == "blocker" for d in review.discoveries)
    verdict = panel.panel_verdict(review)  # three-state projection (spec §1.1)

    problems: list[str] = []
    if review.consensus_go != case.expect_go:
        problems.append(f"consensus_go={review.consensus_go}, expected {case.expect_go}")
    if verdict != case.expect_verdict:
        problems.append(f"verdict={verdict}, expected {case.expect_verdict}")
    if tuple(categories) != tuple(case.expect_categories):
        problems.append(f"categories={categories}, expected {list(case.expect_categories)}")
    if has_blocker != case.expect_blocker:
        problems.append(f"has_blocker={has_blocker}, expected {case.expect_blocker}")

    ok = not problems
    return EvalResult(case.name, ok, "ok" if ok else "; ".join(problems),
                      review.consensus_go, verdict, categories, has_blocker)


def run_suite(cases: tuple[EvalCase, ...] = EVAL_CASES) -> list[EvalResult]:
    """Run the whole eval suite; each result's ``ok`` means the panel matched its
    recorded expectations. All-``ok`` == the second prove-itself gate is green."""
    return [run_case(c) for c in cases]


def suite_passed(results: list[EvalResult] | None = None) -> bool:
    results = results if results is not None else run_suite()
    return bool(results) and all(r.ok for r in results)


def main(argv: list[str] | None = None) -> int:
    results = run_suite()
    for r in results:
        print(f"[{'PASS' if r.ok else 'FAIL'}] {r.name}: {r.detail}")
    passed = suite_passed(results)
    print(f"\neval suite: {'GREEN' if passed else 'RED'} "
          f"({sum(r.ok for r in results)}/{len(results)} cases)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
