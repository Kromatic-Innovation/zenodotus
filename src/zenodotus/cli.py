"""CLI entry point — ``zenodotus review <path>``.

Composes the pipeline end to end:

    deterministic gates (gates.run_all)
        └─ if the floor passes → no-context reviewer panel (panel.review)
             └─ panel-only findings → discovery log
        └─ verdict (floor AND panel consensus); non-zero exit on no-go

Run locally (``pipx install zenodotus`` / ``python -m zenodotus review .``) or as
a deployable routine (container / CI job) — see README "Usage".
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone

from . import gates, panel


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_review(args, *, provider=None, now: str | None = None) -> dict:
    """Execute the review pipeline and return a structured result dict."""
    at = now or _utcnow_iso()

    gate_results = gates.run_all(args.path, include_optional=args.include_optional)
    floor_ok = gates.floor_passed(gate_results)

    result: dict = {
        "path": args.path,
        "floor_passed": floor_ok,
        "gates": [dataclasses.asdict(g) for g in gate_results],
        "panel": None,
        "verdict": "no-go",
    }

    if not floor_ok:
        # Short-circuit: the panel never runs until the deterministic floor passes.
        result["verdict"] = "no-go"
        return result

    panel_result = panel.review(
        args.path,
        n_reviewers=args.reviewers,
        provider=provider,
        gate_results=gate_results,
        log_path=args.log,
        at=at,
    )
    result["panel"] = {
        "consensus_go": panel_result.consensus_go,
        "verdicts": [dataclasses.asdict(v) for v in panel_result.verdicts],
        "discoveries": [dataclasses.asdict(d) for d in panel_result.discoveries],
        "log_path": str(args.log) if args.log else None,
    }
    result["verdict"] = "go" if panel_result.consensus_go else "no-go"
    return result


def _print_human(result: dict, out=None) -> None:
    out = out if out is not None else sys.stdout
    print(f"zenodotus review: {result['path']}", file=out)
    print("\nDeterministic floor:", file=out)
    for g in result["gates"]:
        status = "SKIP" if g["skipped"] else ("PASS" if g["passed"] else "FAIL")
        print(f"  [{status}] {g['name']}: {g['detail']}", file=out)
    print(f"  floor: {'PASSED' if result['floor_passed'] else 'FAILED'}", file=out)

    panel_data = result["panel"]
    if panel_data is None:
        print("\nPanel: not run (floor failed).", file=out)
    else:
        print(f"\nReviewer panel ({len(panel_data['verdicts'])} reviewers):", file=out)
        for v in panel_data["verdicts"]:
            print(f"  [{'go' if v['go'] else 'NO-GO'}] {v['reviewer']}: {v['rationale']}", file=out)
            for f in v["findings"]:
                print(f"      - ({f['severity']}/{f['category']}) {f['finding']}", file=out)
        n_disc = len(panel_data["discoveries"])
        if n_disc:
            where = panel_data["log_path"] or "(not persisted)"
            print(f"  {n_disc} panel-only discoveries logged -> {where}", file=out)

    print(f"\nVERDICT: {result['verdict'].upper()}", file=out)


def main(argv: list[str] | None = None, *, provider=None, now: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zenodotus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="Review a repo/path for OSS release readiness")
    review.add_argument("path", help="Path to the repository under review")
    review.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit a machine-readable verdict")
    review.add_argument("--reviewers", type=int, default=3,
                        help="Number of independent no-context reviewers (default: 3)")
    review.add_argument("--log", default="discoveries.jsonl",
                        help="Discovery-log path (JSONL). Use '' to disable. Default: discoveries.jsonl")
    review.add_argument("--include-optional", action="store_true",
                        help="Also run optional/heavier gates (e.g. OpenSSF Scorecard)")
    args = parser.parse_args(argv)

    if args.command == "review":
        if args.log == "":
            args.log = None
        result = _run_review(args, provider=provider, now=now)
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_human(result)
        # non-zero exit on no-go so CI jobs fail closed
        return 0 if result["verdict"] == "go" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
