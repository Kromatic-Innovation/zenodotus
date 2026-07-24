"""CLI entry point — ``zenodotus review <path>``.

Composes the pipeline end to end:

    deterministic gates (gates.run_all)
        └─ if the floor passes → no-context reviewer panel (panel.review)
             └─ panel-only findings → discovery log
        └─ three-state verdict (pass | warn | block, docs/PANEL_VERDICT_SPEC.md):
           warnings are advisory and exit 0; only a `block` exits non-zero.

The default posture is advisory: panel findings warn, they do not block. Blocking
on a panel finding is opt-in per the maintainer's trust level via ``--fail-on
blocker``. The deterministic floor is a hard gate independent of ``--fail-on`` —
a floor failure is a genuine blocker, not an advisory finding.

Run locally (``pipx install zenodotus`` / ``python -m zenodotus review .``) or as
a deployable routine (container / CI job) — see README "Usage".
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import UTC, datetime

from . import gates, panel, verdict_marker


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- verdict policy ---------------------------------------------------------- #

# --fail-on thresholds: the block threshold applied to the PANEL's contribution.
FAIL_ON_CHOICES = ("blocker", "never")
DEFAULT_FAIL_ON = "never"  # advisory-first: panel findings warn, they do not block


def _derive_verdict(floor_ok: bool, panel_result, *, fail_on: str, shadow: bool) -> str:
    """Combine floor + panel + `--fail-on` + shadow into a `pass|warn|block` verdict.

    Policy on top of the panel's own three-state projection
    (``panel.panel_verdict``, docs/PANEL_VERDICT_SPEC.md §1.1):

    - **Shadow** forces warn-only — nothing blocks. A would-be block (a panel
      block or a floor failure) is presented as an advisory ``warn`` and the
      build exits 0.
    - The **deterministic floor is a hard gate**: a floor failure is a genuine
      blocker, not an advisory finding, so it yields ``block`` regardless of
      ``--fail-on``.
    - A **panel** ``block`` escalates to a hard ``block`` only when the maintainer
      opts in with ``--fail-on blocker``; otherwise (``never``, the default) it
      is advisory and reported as ``warn``.
    """
    panel_state = panel.panel_verdict(panel_result) if panel_result is not None else panel.PASS

    if shadow:
        if not floor_ok or panel_state in (panel.WARN, panel.BLOCK):
            return panel.WARN
        return panel.PASS

    if not floor_ok:
        return panel.BLOCK

    if panel_state == panel.BLOCK:
        return panel.BLOCK if fail_on == "blocker" else panel.WARN
    return panel_state  # WARN or PASS


def _attach_verdict_marker(result: dict, args, at: str) -> dict:
    """Attach the durable cross-repo verdict marker when ``--emit-verdict-marker``.

    Records the effective verdict against the reviewed tree's git HEAD in the
    ``<!-- zenodotus-verdict: v1 ... -->`` format (issue #54) so a separate tool
    (hestia's ``oss-status``) can read "has zenodotus cleared this repo?" and
    detect staleness by SHA. The marker is attached to the result (surfaced in
    ``--json`` and printed in human mode); posting it is the caller's job.
    """
    if not getattr(args, "emit_verdict_marker", False):
        return result
    result["verdict_marker"] = verdict_marker.render_verdict_marker(
        repo=verdict_marker.resolve_repo(args.path, getattr(args, "repo", None)),
        sha=verdict_marker.head_sha(args.path),
        verdict=result["verdict"],
        ran_at=at,
    )
    return result


def _run_review(args, *, provider=None, now: str | None = None) -> dict:
    """Execute the review pipeline and return a structured result dict."""
    at = now or _utcnow_iso()

    gate_results = gates.run_all(args.path, include_optional=args.include_optional)
    floor_ok = gates.floor_passed(gate_results)

    shadow = getattr(args, "shadow", False)
    fail_on = getattr(args, "fail_on", DEFAULT_FAIL_ON)
    result: dict = {
        "path": args.path,
        "shadow": shadow,
        "fail_on": fail_on,
        "floor_passed": floor_ok,
        "gates": [dataclasses.asdict(g) for g in gate_results],
        "panel": None,
        # `panel_verdict` is the panel's OWN raw three-state projection (before
        # the floor/--fail-on/shadow policy) so a block downgraded to warn stays
        # visible; None when the panel did not run. `verdict`/`state` are the
        # effective, policy-applied verdict (state is a spec §1.2 field alias).
        "panel_verdict": None,
        "verdict": panel.BLOCK,
        "state": panel.BLOCK,
        # Durable cross-repo verdict marker (issue #54); populated only when
        # --emit-verdict-marker is set, else stays None.
        "verdict_marker": None,
    }

    # Normally the panel short-circuits — it never runs until the deterministic
    # floor passes. In SHADOW mode it runs regardless, so we accumulate panel
    # discoveries on real release candidates even when the floor fails; the
    # gate_results still dedupe findings a failing gate already caught.
    if not (floor_ok or shadow):
        result["verdict"] = _derive_verdict(floor_ok, None, fail_on=fail_on, shadow=shadow)
        result["state"] = result["verdict"]
        return _attach_verdict_marker(result, args, at)

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
    result["panel_verdict"] = panel.panel_verdict(panel_result)
    result["verdict"] = _derive_verdict(floor_ok, panel_result, fail_on=fail_on, shadow=shadow)
    result["state"] = result["verdict"]
    return _attach_verdict_marker(result, args, at)


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

    verdict = result["verdict"]
    label = verdict.upper()
    if result.get("shadow"):
        # Shadow is always advisory (warn-only); say so plainly.
        print(f"\nVERDICT: {label}  (SHADOW — advisory only, build not blocked)", file=out)
    elif verdict == panel.PASS:
        print(f"\nVERDICT: {label}", file=out)
    elif verdict == panel.WARN:
        if result.get("panel_verdict") == panel.BLOCK:
            print(f"\nVERDICT: {label}  (advisory — a block-level finding is present, but "
                  f"blocking is disabled via --fail-on never; warnings do NOT block, exit 0)",
                  file=out)
        else:
            print(f"\nVERDICT: {label}  (advisory — warnings do NOT block, exit 0)", file=out)
    else:  # block
        print(f"\nVERDICT: {label}  (blocking — exit non-zero)", file=out)

    marker = result.get("verdict_marker")
    if marker:
        print("\nDurable verdict marker (post as a comment on the target repo so "
              "hestia's oss-status can read it):", file=out)
        print(marker, file=out)


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
    review.add_argument("--fail-on", dest="fail_on", choices=FAIL_ON_CHOICES,
                        default=DEFAULT_FAIL_ON,
                        help="Block threshold for PANEL findings (the deterministic floor "
                             "always blocks regardless): 'blocker' exits non-zero on a "
                             "blocker-severity finding or reviewer no-go; 'never' (default) "
                             "keeps panel findings advisory — they WARN but never block "
                             "(exit 0). Blocking is opt-in per the maintainer's trust level.")
    review.add_argument("--shadow", action="store_true",
                        help="Shadow mode: run the panel even if the floor fails, append "
                             "discoveries to the log, and NEVER fail the build (exit 0). "
                             "The recommended way to accumulate prove-itself evidence on "
                             "live release candidates.")
    review.add_argument("--emit-verdict-marker", action="store_true",
                        dest="emit_verdict_marker",
                        help="Emit a durable, machine-readable cross-repo verdict marker "
                             "(<!-- zenodotus-verdict: v1 ... -->) recording the verdict "
                             "against the reviewed tree's git HEAD. Post it as a comment on "
                             "the target repo so hestia's oss-status command can read whether "
                             "zenodotus has cleared that repo (issue #54).")
    review.add_argument("--repo", default=None,
                        help="owner/name slug recorded in the verdict marker (--emit-verdict-"
                             "marker). Defaults to the reviewed tree's git 'origin' remote, "
                             "then the directory name.")
    args = parser.parse_args(argv)

    if args.command == "review":
        if args.log == "":
            args.log = None
        result = _run_review(args, provider=provider, now=now)
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_human(result)
        # Three-state exit contract (docs/PANEL_VERDICT_SPEC.md §1): pass/warn
        # exit 0; only a block exits non-zero. Shadow is always warn-only, so it
        # is covered by the same rule, but we short-circuit it explicitly.
        if args.shadow:
            return 0
        return 0 if result["verdict"] in (panel.PASS, panel.WARN) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
