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
   This is a standalone Python implementation, not a dependency on
   [panelist](https://github.com/Kromatic-Innovation/panelist) (the org's
   general-purpose persona-panel engine) — see zenodotus#36 for the rationale.
   Both panels satisfy a shared verdict shape instead of sharing code; the
   spec is [`docs/PANEL_VERDICT_SPEC.md`](PANEL_VERDICT_SPEC.md).
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

## Prove-itself protocol (historical gate — now the value hypothesis under test)

The public flip and PyPI publish have **already happened** (zenodotus 0.1.0). The
"prove itself" protocol was originally the gate that held them back; it is kept
here as the framing for *why the discovery-log and eval-suite work still matters*
now that publication is done. The two conditions were:
1. The discovery log contains a meaningful set of **panel-only** findings
   (things the deterministic floor missed) — evidence the panel adds value.
2. Those logged discoveries are distilled into a small **eval suite** (fixtures
   + expected panel verdicts) that the panel passes reproducibly.

The eval suite lives in [`tests/evals/suite.py`](../tests/evals/suite.py): a
manifest of discovery-derived cases (each a fixture repo + its expected panel
verdict) plus a runner. It remains the artifact that evidences the panel's value,
and it is enforced green in CI:

```
python tests/evals/suite.py     # PASS/FAIL per case + GREEN/RED summary
```

The suite runs fully offline via committed cassettes (no API key, no network),
and it deliberately exercises **both** outcomes: a repo the panel correctly
blocks (`mediocre-readme`) and a repo it correctly passes (`clean-complete` — a
complete, well-licensed repo that the pre-#30 `gather_context` false-blocked;
see issue #30). `tests/test_evalsuite.py` asserts the suite stays green and
reproducible in CI.

The "flip to public" and "publish" work is complete; the value hypothesis — that
the panel earns its keep — stays under continuous test via the discovery log and
the eval suite.

## Deterministic panel evals (offline, reproducible)

The panel is LLM-backed, so it is non-deterministic and costs money — neither is
acceptable in CI. A **record/replay cassette** layer (`src/zenodotus/cassette.py`)
solves both: real provider responses are recorded once against a committed
fixture repo (`tests/evals/fixtures/`) and replayed thereafter from a committed
cassette (`tests/evals/cassettes/`). `CassetteProvider` implements the same
`Provider` protocol as the live backend; each interaction is keyed by a stable
hash of `(reviewer_id, gathered-context)`, so an unchanged fixture always
replays exactly. CI runs the panel + evals **fully offline and reproducibly** —
no API key, no network. This is the substrate the eval suite (fixtures + expected
panel verdicts, the second prove-itself gate above) is built on.

Refresh a cassette against the live API (run manually, needs a key):

```python
rec = CassetteProvider("tests/evals/cassettes/x.json", mode="record",
                       inner=AnthropicProvider())
panel.review("tests/evals/fixtures/x", provider=rec, at="...")
rec.save()
```

## Leak self-check (belt-and-suspenders before the public flip)

Independently of the prove-itself gates above, a CI **leak self-check**
(`src/zenodotus/leakcheck.py`, run by the `leak-check` job) scans the whole repo
for strings that should never appear in a public tree. The built-in denylist
targets *accidental* leaks that are generic to any codebase — local developer
machine paths and private/internal network hostnames. Anything project-specific
(personal names, private identifiers, internal service names) is supplied
per-repo as a list of regex patterns in a denylist file, so the scanner needs no
code change to tighten. See the module's `DEFAULT_DENYLIST` for the built-in
patterns. That per-repo denylist file (`.zenodotus-leakcheck.txt`) is
**optional** — the built-in defaults work without it, so this repo ships no such
file. The `leak-check` job runs on **every PR** (it is aggregated into the
required `ci-required` status check, so it must be green to merge) and
**must be green before the public flip** — it is a hard prerequisite for the
flip-to-public issue. Run it locally with
`python -m zenodotus.leakcheck .`.
