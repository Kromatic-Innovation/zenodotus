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

Bootstrap scaffold. Implementation is tracked in this repo's issues and built
incrementally. Not yet functional.

## How it will work

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

Runs **locally** (`pipx install zenodotus` / `python -m zenodotus`) or as a
**deployable routine** (container / CI job).

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
