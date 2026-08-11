# AGENTS.md — zenodotus

LLM-agnostic agent guidance for this repo.

## What this is

An OSS release-readiness gate — deterministic pre-gates (composing OpenSSF
Scorecard, REUSE, Gitleaks, and pyroma) plus a no-context reviewer panel.

## Branch policy

- Default branch: `develop`; open PRs against `develop`.
- Releases are tagged from `main` after a `develop → main` fast-forward.

## Strategy tier

**T3.** A public OSS release-review gate.

Band rationale: `code-workspace-config/docs/strategy/portfolio.md`. Canonical
strategy: `code-workspace-config/docs/strategy/README.md`. Strategy is stated in
prose there and nowhere else — do not restate or paraphrase it here.
