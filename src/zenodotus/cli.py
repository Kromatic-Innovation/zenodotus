"""CLI entry point.  `zenodotus review <path>`  (scaffold)."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zenodotus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="Review a repo/path for OSS release readiness")
    review.add_argument("path", help="Path to the repository under review")
    review.add_argument("--json", action="store_true", help="Emit machine-readable verdict")
    args = parser.parse_args(argv)

    if args.command == "review":
        # TODO(#build): run gates.run_all() -> panel.review() -> discovery_log + verdict
        print("zenodotus: not yet implemented — see repo issues", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
