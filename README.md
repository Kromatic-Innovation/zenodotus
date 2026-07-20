# Zenodotus

**An OSS release-readiness gate: deterministic pre-gates + a no-context reviewer panel.**

Most "is this repo open-source ready?" checks are mechanical and already solved
by great tools (OpenSSF Scorecard, REUSE, Gitleaks, pyroma, twine, GitHub
Community Standards). Zenodotus **composes those as a hard floor**, then adds the
part tools don't do: a panel of independent, *no-context* reviewers that judge
the things a linter can't — is the README coherent to an outsider, is the scope
and naming sensible, is there internal/proprietary leakage that isn't a
"secret", is this actually useful and finished?

The novel piece is the **reviewer-panel-as-gate**, not the checklist.

## Status

Core pipeline (deterministic gates → no-context reviewer panel → discovery log →
verdict) is wired end to end via `zenodotus review`. Still pre-1.0 and under the
"prove itself" milestone (docs/CONCEPT.md) — it stays private until the discovery
log demonstrates the panel earns its keep.

## How it works

```
zenodotus review <path-or-repo>
  ├─ 1. Deterministic pre-gates (must all pass)  ── gates.py
  │      license · community files · secrets · packaging · security posture
  ├─ 2. No-context reviewer panel (judgment)      ── panel.py
  │      N independent reviewers, each blind to the others, render go/no-go
  └─ 3. Discovery log + verdict                    ── discovery_log.py
         every panel-only finding (something the deterministic gates MISSED)
         is logged — this is how the panel earns its keep.
```

The command short-circuits: the panel only runs once the deterministic floor
passes. The final verdict is `floor AND panel-consensus`, and the process exits
non-zero on a no-go so it fails closed in CI.

## Usage

### Local

```bash
pipx install zenodotus            # or: pip install "zenodotus[llm]"
export ANTHROPIC_API_KEY=sk-...   # the default reviewer provider (Claude); your own key
zenodotus review /path/to/repo                     # human-readable verdict
zenodotus review /path/to/repo --json              # machine-readable
python -m zenodotus review . --reviewers 5 --log discoveries.jsonl
```

Options: `--json` (machine-readable output), `--reviewers N` (panel size, default 3),
`--log PATH` (discovery-log JSONL path; `--log ''` disables), `--include-optional`
(also run heavier optional gates such as OpenSSF Scorecard). Exit code is `0` on go,
non-zero on no-go.

### Deployable routine (container / CI job)

Run the same command in a container or CI step to gate a release candidate. A
minimal container:

```dockerfile
FROM python:3.11-slim
RUN pip install "zenodotus[llm,tools]"
ENTRYPOINT ["zenodotus", "review"]
```

```bash
docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/repo" zenodotus /repo --json
```

As a GitHub Actions step (fails the job on a no-go via the non-zero exit):

```yaml
- name: Zenodotus release-readiness gate
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: |
    pip install "zenodotus[llm,tools]"
    zenodotus review . --json --log discoveries.jsonl
```

The deterministic floor (`gates.py`) composes external tools as optional
subprocesses and degrades gracefully when one is absent. The exact tools,
pinned versions, and invocations are documented in
[docs/CONCEPT.md → Tools wired](docs/CONCEPT.md#tools-wired-into-the-deterministic-floor-srczenodotusgatespy).
Install the pip-installable helpers with `pip install "zenodotus[tools]"`.

## Why the discovery log matters

Zenodotus only justifies its existence if the panel finds things the free
deterministic tools do not. Every such finding is recorded to a structured
**discovery log** (`discovery_log.py`). The repo does not graduate to public /
published until the log proves the panel earns its keep — see
[docs/CONCEPT.md](docs/CONCEPT.md) and the "prove itself" issues.

## License

Apache-2.0 — chosen for its explicit patent grant (see docs/POSITIONING.md).
