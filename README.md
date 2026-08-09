# Zenodotus

![zenodotus: three judge archetypes — developer, compliance officer, security reviewer — stamping verdicts at a checkpoint gate](docs/assets/hero.png)

**An OSS release-readiness review gate: deterministic pre-gates + a no-context reviewer panel.** It renders a three-state verdict — **pass / warn / block** — where warnings are advisory and **never block** (exit 0). Blocking is reserved for genuine blockers and is opt-in per the maintainer's trust level; the default posture is advisory.

**Use case:** you're about to open-source a repo and want more than a green CI badge before you flip it public — something that catches the stuff linters structurally can't: leaked internal context, a README that only makes sense to people who already work here, scope creep, an unfinished feature dressed up as done.

**Differentiator:** every "is this OSS-ready" tool on the market is a checklist — license present, CoC present, no secrets. Zenodotus composes those (via existing tools: Scorecard, REUSE, Gitleaks, pyroma) as a hard floor, then adds what checklists can't do: independent, no-context reviewers who render a judgment call, not a checkbox. Verdicts get logged; every panel-only finding (something the deterministic floor missed) is the evidence the panel earns its keep.

**Why:** a repo can pass every automated check and still be unreadable, still leak org-internal assumptions, still not actually be finished — because none of that is mechanically checkable. Zenodotus exists because "the linters are green" and "this is actually ready for strangers" are different questions, and only one of them has been getting asked.

Most "is this repo open-source ready?" checks are mechanical and already solved
by great tools (OpenSSF Scorecard, REUSE, Gitleaks, pyroma, twine, GitHub
Community Standards). Zenodotus **composes those as a hard floor**, then adds the
part tools don't do: a panel of independent, *no-context* reviewers that judge
the things a linter can't — is the README coherent to an outsider, is the scope
and naming sensible, is there internal/proprietary leakage that isn't a
"secret", is this actually useful and finished?

The novel piece is the **reviewer-panel-as-gate**, not the checklist.

> Zenodotus's panel (`panel.py`) is a standalone Python implementation, purpose-built
> for release-gate judgment calls. It's conceptually related to (but does not
> depend on) [**panelist**](https://github.com/Kromatic-Innovation/panelist) —
> the org's general-purpose synthetic persona-panel engine (npm). They're kept
> separate by design; both satisfy a shared verdict shape instead of sharing
> code — see [`docs/PANEL_VERDICT_SPEC.md`](docs/PANEL_VERDICT_SPEC.md)
> (rationale: zenodotus#36).

## Status

**Public and published** — `zenodotus` is on PyPI (`pip install zenodotus`)
and this repo is open source. The core pipeline (deterministic gates → no-context
reviewer panel → discovery log → verdict) is wired end to end via
`zenodotus review`. Still pre-1.0: the "prove itself" work (docs/CONCEPT.md) —
accumulating panel-only discoveries and distilling them into the eval suite — now
serves as ongoing validation that the panel earns its keep, not as a gate holding
back a publication that has already happened.

## How it works

```
zenodotus review <path-or-repo>
  ├─ 1. Deterministic pre-gates (must all pass)  ── gates.py
  │      license · community files · secrets · packaging · security posture
  ├─ 2. No-context reviewer panel (judgment)      ── panel.py
  │      N independent reviewers, each blind to the others, raise
  │      severity-graded findings (blocker / major / minor)
  └─ 3. Discovery log + three-state verdict        ── discovery_log.py
         every panel-only finding (something the deterministic gates MISSED)
         is logged — this is how the panel earns its keep.
```

The command short-circuits: the panel only runs once the deterministic floor
passes. It then renders a **three-state verdict** — `pass` / `warn` / `block`
(see [`docs/PANEL_VERDICT_SPEC.md`](docs/PANEL_VERDICT_SPEC.md)):

- **`pass`** — nothing to act on. Exit `0`.
- **`warn`** — advisory findings exist, but none is a blocker. **Warnings never
  block** — exit `0`. This is the default posture: panel findings warn, they do
  not fail your build.
- **`block`** — a genuine blocker. Exit non-zero. A panel finding only escalates
  to `block` when you opt in with `--fail-on blocker`; the deterministic floor
  (a missing license, a leaked secret) is a hard gate and always blocks.

So the panel is a **review gate**, not a hard merge gate: it complements linters
with judgment-level review and, by default, advises rather than fails closed.
Blocking remains available (`--fail-on blocker`) but is reserved for genuine
blockers, opt-in per the maintainer's trust level.

## Prerequisites & setup

Zenodotus **composes** existing tools. Some ship with the package; others are
separate binaries you install out of band. **Every external tool is optional:
if it is absent, its gate reports `skipped` and the floor still runs** — see
[Skipped is not passed](#skipped-is-not-passed) below for why that matters.

### 1. Install the package (+ optional extras)

```bash
pip install "zenodotus[llm,tools]"   # or: pipx install "zenodotus[llm,tools]"
```

| Extra    | Provides                                             | Needed for |
| -------- | --------------------------------------------------- | ---------- |
| _(base)_ | the `zenodotus` CLI and deterministic gates         | always     |
| `llm`    | the default reviewer provider (Anthropic Claude)    | a live panel run |
| `tools`  | `pyroma` + `twine` (the `packaging_ok` gate)        | packaging checks |

A live panel run also needs an API key: `export ANTHROPIC_API_KEY=sk-...`.

### 2. Install the out-of-band binaries (optional)

These are Go/Ruby tools that are **not** pip-installable. Install only the ones
whose gate you want to run:

| Binary      | Gate it enables      | Install                                             | Skipped if absent |
| ----------- | -------------------- | --------------------------------------------------- | ----------------- |
| `gitleaks`  | `no_secrets`         | `brew install gitleaks` / [releases][gl]            | secret scan does not run |
| `licensee`  | `license_present` (enrichment only — a pure-Python check still runs) | `gem install licensee` | license enrichment does not run |
| `scorecard` | `security_posture` (optional, off unless `--include-optional`) | [ossf/scorecard][sc] | posture check does not run |

[gl]: https://github.com/gitleaks/gitleaks/releases
[sc]: https://github.com/ossf/scorecard

The exact versions and invocations are documented in
[docs/CONCEPT.md → Tools wired](docs/CONCEPT.md#tools-wired-into-the-deterministic-floor-srczenodotusgatespy).

### Skipped is not passed

A gate whose tool is absent reports **`skipped`, which is neither `passed` nor
`failed`** — the check simply did not run. `floor_passed()` treats a skipped
gate as non-blocking (so a missing optional tool never fails your build), which
means a green-looking verdict can still hide checks that never executed. If you
need a specific gate enforced, install its tool above and confirm the gate
reports `passed` (not `skipped`) — `zenodotus review . --json` lists each gate's
status explicitly.

## Usage

### Local

```bash
pipx install zenodotus            # or: pip install "zenodotus[llm]"
export ANTHROPIC_API_KEY=sk-...   # the default reviewer provider (Claude); your own key
zenodotus review /path/to/repo                     # human-readable verdict
zenodotus review /path/to/repo --json              # machine-readable
python -m zenodotus review . --reviewers 5 --log discoveries.jsonl
```

Options:

- `--json` — machine-readable output (includes each gate's `skipped`/`passed` status, the three-state `verdict`, and the raw `panel_verdict` before policy).
- `--reviewers N` — panel size (default 3).
- `--log PATH` — discovery-log JSONL path; `--log ''` disables logging.
- `--include-optional` — also run heavier optional gates such as OpenSSF Scorecard.
- `--fail-on {blocker,never}` — block threshold for **panel** findings. `never`
  (default) keeps panel findings advisory (they `warn`, never block); `blocker`
  makes a blocker-severity finding or a reviewer no-go exit non-zero. The
  deterministic floor blocks regardless.
- `--shadow` — advisory, non-blocking run (see [Shadow mode](#shadow-mode-recommended-for-accumulating-evidence) below).
- `--emit-verdict-marker` — also emit a durable, machine-readable cross-repo verdict marker (see [Cross-repo review](#cross-repo-review-verdict-marker) below).
- `--repo OWNER/NAME` — the slug recorded in that marker (defaults to the reviewed tree's git `origin` remote, then its directory name).
- `--reviewer-tools tool1,tool2` — explicit tool allowlist for reviewers ([issue #79](https://github.com/Kromatic-Innovation/zenodotus/issues/79)). Default: unset, i.e. fully isolated — reviewers get no tools at all, no matter what a provider requests. Anything not named here (including a tool-search/discovery capability) is denied, not implicitly reachable; the effective tool set and any denied attempt are reported (`--json` → `panel.isolation`).

Exit code follows the three-state verdict: `0` for `pass` and `warn` (warnings
never block), non-zero only for `block`. By default (`--fail-on never`) a panel
finding never blocks — you opt into blocking with `--fail-on blocker`. The
deterministic floor (missing license, leaked secret) is a hard gate and blocks
regardless.

### Library (Python)

```python
from zenodotus.panel import review

# State the model at the call site — no env var, no hand-built provider:
panel = review("/path/to/repo", model="claude-sonnet-5")
```

**There is no built-in default model.** Zenodotus runs one review per reviewer,
so the model choice is a cost decision — and it is yours, not this library's.
`model` resolves with the precedence (highest first): an explicit `model=`
kwarg → an explicitly passed `provider=`'s own configured model → the
`ZENODOTUS_MODEL` env var → **`ValueError`**. The Anthropic SDK resolves
credentials from the environment but never a model, so there is nothing ambient
to inherit; erroring is louder than calling the API with an unset model.

Passing **both** `model=` and a caller-built `provider=` raises `ValueError` —
a supplied provider owns its own model. To run a specific model on a custom
provider, configure it on that provider before passing it.

Current model ids are listed in the [Anthropic models
overview](https://platform.claude.com/docs/en/about-claude/models/overview).

**On the CLI**, set `ZENODOTUS_MODEL` — the CLI has no `--model` flag, so this
is how you state the model for `zenodotus review`:

```bash
export ZENODOTUS_MODEL=claude-sonnet-5
zenodotus review .
```

### Shadow mode (recommended for accumulating evidence)

```bash
zenodotus review . --shadow --log discoveries.jsonl
```

`--shadow` runs Zenodotus on real release candidates **without blocking** them:
the reviewer panel runs even when the deterministic floor fails, every panel-only
finding is appended to the discovery log, and the process **always exits 0** — the
verdict is reported (as an advisory `warn`) but never blocks. Shadow is folded
into the three-state model as **warn-only**: any would-be `block` is presented as
`warn`. This is the **recommended way to accumulate "prove-itself" evidence** on
live RCs (docs/CONCEPT.md): gather a meaningful set of panel-only discoveries
safely, before Zenodotus blocks anything. Add it as a non-required CI step first,
review the accumulated log, and — once the evidence justifies it — tighten to a
blocking panel by dropping `--shadow` **and** setting `--fail-on blocker`.

### Cross-repo review (verdict marker)

Zenodotus can review an **external** repo — not just itself — and record a
durable verdict a separate tool can read. `zenodotus review <path>` already
accepts any checkout; add `--emit-verdict-marker` to also emit a small,
machine-readable marker recording the verdict against that tree's git HEAD:

```bash
zenodotus review /path/to/ideate-core --emit-verdict-marker \
  --repo Kromatic-Innovation/ideate-core
```

```html
<!-- zenodotus-verdict: v1
     repo: Kromatic-Innovation/ideate-core
     sha: <full commit SHA reviewed>
     verdict: pass | warn | block
     ran_at: <ISO-8601>
     runner: zenodotus vX.Y.Z
-->
```

Post that marker as a comment on the target repo. A consumer (e.g. hestia's
`oss-status` command) reads it to answer "has zenodotus cleared this repo's
current `main`?" and detects staleness for free by comparing the marker's `sha`
to the target's current HEAD — mismatch (or the `unknown` sentinel when the tree
was not a git checkout) means "stale, re-run", never a silent false "cleared".
Zenodotus only *writes* the marker; it stays dependency-free and does not post to
GitHub itself. Full format spec: [`docs/CROSS_REPO_VERDICT.md`](docs/CROSS_REPO_VERDICT.md).

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

As a GitHub Actions step. By default the panel is **advisory** — it surfaces a
verdict and discoveries but exits `0` on `warn`, so it never fails the job on a
panel finding (only the deterministic floor blocks). Add `--fail-on blocker` when
you want a blocker-severity finding (or a reviewer no-go) to fail the job:

```yaml
- name: Zenodotus release-readiness review
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: |
    pip install "zenodotus[llm,tools]"
    # advisory by default; add --fail-on blocker to make panel blockers fail CI
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
**discovery log** (`discovery_log.py`). The log is the running evidence that the
panel earns its keep — see [docs/CONCEPT.md](docs/CONCEPT.md) and the "prove
itself" issues for how those discoveries feed the eval suite.

## License

Apache-2.0 — chosen for its explicit patent grant (see docs/POSITIONING.md).
