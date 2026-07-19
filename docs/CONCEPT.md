# Concept & the "prove itself" protocol

## The gate

1. **Deterministic floor** — compose existing, permissively-licensed tools.
   The floor must pass before the panel runs. Candidates:
   - License present + valid — REUSE / `licensee` / GitHub Community Standards
   - Community files (README, CONTRIBUTING, CoC, SECURITY) — GitHub API / Repolinter-style
   - No leaked secrets — Gitleaks
   - PyPI packaging hygiene — `pyroma` + `twine check`
   - Security posture — OpenSSF Scorecard (optional, heavier)
2. **Judgment panel** — N independent no-context reviewers (default provider:
   Anthropic Claude; provider-agnostic). Each reviewer is blind to the others
   and to internal context, and renders a structured go/no-go with rationale.
3. **Verdict** — deterministic floor AND panel consensus.

## Discovery log (load-bearing)

Every time the panel flags something the deterministic floor did NOT catch, it
is appended to the discovery log with:

- `finding` — what was wrong
- `category` — coherence | naming | scope | leakage | usefulness | doc-quality | other
- `caught_by` — always "panel" for a discovery entry
- `missed_by_deterministic` — true (the whole point)
- `severity` — blocker | major | minor
- `reviewer` / `rationale`

## Prove-itself gating (blocks the public flip + publish)

Zenodotus is NOT made public or published to a registry until:
1. The discovery log contains a meaningful set of **panel-only** findings
   (things the deterministic floor missed) — evidence the panel adds value.
2. Those logged discoveries are distilled into a small **eval suite** (fixtures
   + expected panel verdicts) that the panel passes reproducibly.

Only then do the "flip to public" and "publish" issues unblock. Until then the
repo stays private and the value hypothesis stays under test.
