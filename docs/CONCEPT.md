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

### Tools wired into the deterministic floor (`src/zenodotus/gates.py`)

Zenodotus **composes** these; it does not reimplement them. Each external tool
is invoked as a subprocess and is **optional** — a gate whose tool is absent
reports `skipped=True` (surfaced in the verdict) rather than crashing, so the
floor degrades gracefully. `floor_passed()` treats skipped gates as
non-blocking; only a non-skipped failing gate fails the floor.

| Gate | Tool | Version wired | Invocation | Install |
|------|------|---------------|-----------|---------|
| `license_present` | pure-Python file check, then `licensee` (optional enrichment) | licensee ≥ 9.16 | `licensee detect --json <path>` | `gem install licensee` |
| `community_files` | pure-Python presence check | n/a (no external tool) | README + CONTRIBUTING required; CODE_OF_CONDUCT + SECURITY recommended | built in |
| `no_secrets` | Gitleaks | gitleaks ≥ 8.18 | `gitleaks detect --no-git --source <path> --redact --exit-code 1` | `brew install gitleaks` / [releases](https://github.com/gitleaks/gitleaks/releases) |
| `packaging_ok` | pyroma | pyroma ≥ 4.2 | `pyroma --min 8 <path>` | `pip install "zenodotus[tools]"` |
| `security_posture` (optional, off by default) | OpenSSF Scorecard | scorecard ≥ 5.0 | `scorecard --local=<path> --format=json` | [ossf/scorecard](https://github.com/ossf/scorecard) |

`twine check` is complementary to `pyroma`: it validates a **built** `dist/`
(`twine` ≥ 5.0, `pip install "zenodotus[tools]"`), so it runs at the CLI layer
when packaging artifacts exist rather than against the bare source tree.

The pip-installable helpers (`pyroma`, `twine`) ship via the `tools` extra:
`pip install "zenodotus[tools]"`. The Go/Ruby binaries (`gitleaks`, `licensee`,
`scorecard`) are installed out of band per the table above; without them the
corresponding gate simply reports `skipped`.

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
