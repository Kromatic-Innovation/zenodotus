# Changelog

All notable changes to Zenodotus are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning convention

Zenodotus is **pre-1.0 (0.x)**. MAJOR is reserved for the 1.0 stability
commitment and stays unused, so MINOR and PATCH do double duty:

- **PATCH** (`0.x.Y` → `0.x.Y+1`) — no consumer-visible behaviour change.
- **MINOR** (`0.x.Y` → `0.x+1.0`) — any consumer-visible *addition*, **or** any
  *breaking* change. Because MAJOR is off-limits pre-1.0, a breaking change still
  lands as MINOR — which is surprising to a strict-semver reader. **Every MINOR
  entry therefore states its breaking status explicitly**, rather than leaving
  the version number to imply it.

## [Unreleased]

### Changed

- Project status is now **maintenance**: the README Status section says so
  (bug and security fixes only, best-effort; no new features planned) and
  `SECURITY.md` matches. `SECURITY.md` now names email as the reporting route,
  because GitHub private vulnerability reporting is not enabled on this
  repository. No code change.

## [0.4.0] - 2026-11-24

Minor release: configurable review. `zenodotus review` now reads an optional
per-repo `.zenodotus.json`, can review only a release's diff, and runs
named reviewer lenses with prior rulings and a nit bar.

**Summary.**

- **Breaking and behaviour changes.** There is no built-in default model any
  more: set `ZENODOTUS_MODEL`, pass `--model`, or pass `model=` to
  `review()`, or the CLI exits 2. With no `.zenodotus.json` the CLI also has
  new defaults: three lens reviewers instead of three generic ones, diff scope
  for patch and minor releases when a prior tag is given, prior rulings on,
  and a strict nit bar. The library's `panel.review()` defaults are
  unchanged apart from the model.
- **Experimental surface.** None is marked experimental. The new
  `.zenodotus.json` keys and CLI flags are covered by the versioning
  convention above like any other public surface.
- **Security-relevant changes.** The leak self-check now scans tracked files
  under `dist/` and `build/` too, so a check that passed before may now flag
  a leak there. It no longer flags its own custom `--denylist-file`. Reviewer
  tool isolation is unchanged: deny by default, with a panel-wide allowlist.
- **Upgrade steps.** Set `ZENODOTUS_MODEL` (or pass `--model`) before running
  the CLI. To keep the 0.3.0 panel, pass `--reviewers 3 --nit-bar standard
  --scope full`, or commit
  `{"nit_bar": "standard", "cli": {"reviewers": 3}}` as `.zenodotus.json`.

### Breaking-change status

**Breaking for anyone who relied on the implicit default model**, and a
**behaviour change for every CLI run with no `.zenodotus.json`**: the CLI's
no-config defaults now match the workspace release-gate skill (see *Changed*
below). Per the versioning convention above this lands as a **MINOR** bump
when released. The library's `panel.review()` defaults are unchanged.

### Added

- **Configurable review** ([#134](https://github.com/Kromatic-Innovation/zenodotus/issues/134)).
  `zenodotus review` reads an optional, committed `.zenodotus.json` at the
  reviewed repo's root, the same file the workspace release-gate skill reads.
  Precedence: CLI flag, then `ZENODOTUS_MODEL` (model only), then the file,
  then the default. `--config PATH` reads another file and `--no-config`
  ignores it. An invalid value, an unknown key under `cli` or at the top
  level, or a duplicate key exits 2 with a message naming the dotted key.
  The skill-only keys `disposition`, `trivial_fix_max_lines` and `rerun` are
  accepted and ignored. New module `zenodotus.config`.
- Shared keys with the skill's names and defaults: `scope.patch|minor|major`
  (`diff`/`full`), `personas`, `prior_rulings`, `nit_bar`. Package-only keys
  under `cli`: `reviewers`, `fail_on`, `include_optional`, `reviewer_tools`,
  `shadow`, `model`, `lenses` (custom `{id, focus}` lenses) and `personas`.
- **Diff scope by bump class.** New `--prior-tag REF` (alias `--base-ref`),
  `--version`, `--bump-class patch|minor|major|none` and `--scope`. Without
  `--bump-class`, the class is derived from `--prior-tag` and `--version` by
  SemVer comparison. With no prior tag the class is `none` and the scope is
  always `full`. In `diff` scope reviewers also get the changed-file list and
  the release diff and report only on the changes.
- **Reviewer lenses** with the skill's slugs: `drive-by-installer`,
  `production-evaluator`, `maintainers-maintainer`, `drive-by-contributor`.
  New `--personas`. Reviewers stay no-context and blind to each other.
- **Prior rulings.** New `--prior-findings PATH` and `--prior-rulings on|off`.
  Reviewers are told not to re-raise an already-ruled point; a re-raised one
  is marked `repeat: true`. Format: `docs/PANEL_VERDICT_SPEC.md` §5 (spec 1.3).
- **Nit bar.** New `--nit-bar strict|standard`.
- New `--model` flag, above `ZENODOTUS_MODEL` in precedence.
- New `--no-shadow` and `--no-include-optional`, so a flag can turn off a
  `true` set in the file.
- `--json` records `bump_class`, `config_file` and `settings` (every
  effective setting as `{value, source}`, the skill's shape). Every finding
  carries `in_diff` and `repeat`. A finding with `in_diff: false` or
  `repeat: true` is reported as a warning and never blocks, whatever
  `--fail-on` says. Discovery-log records tag them `out-of-diff` / `repeat`.
- `panel.review()` gains `scope`, `base_ref`, `lenses`, `prior_findings` and
  `nit_bar` keyword arguments. Their defaults reproduce the earlier panel.

### Changed

- **CLI defaults with no `.zenodotus.json`** ([#134](https://github.com/Kromatic-Innovation/zenodotus/issues/134)).
  These match the skill and stop the "new nits every patch release" loop:
  - the panel is one reviewer per default lens (`drive-by-installer`,
    `production-evaluator`, `maintainers-maintainer`) instead of three
    generic reviewers. `--reviewers N` still runs N generic reviewers;
  - the scope is `diff` for patch and minor releases when a prior tag is
    given (`full` for major, and always `full` without a prior tag);
  - prior rulings are `on` (they apply when `--prior-findings` is given);
  - the nit bar is `strict`.

  To get the old behaviour back, pass `--reviewers 3 --nit-bar standard
  --scope full`, or put `{"nit_bar": "standard", "cli": {"reviewers": 3}}` in
  `.zenodotus.json`.
- **Packaging extras.** The `tools` extra now installs only `pyroma`. It no
  longer installs `twine`, which no code path ran
  ([#115](https://github.com/Kromatic-Innovation/zenodotus/issues/115)). The
  `dev` extra pins `ruff==0.17.3`.

### Removed

- **No built-in default model** ([#87](https://github.com/Kromatic-Innovation/zenodotus/issues/87)).
  `panel.DEFAULT_MODEL` and its hardcoded `claude-opus-4-8` literal are gone.
  Zenodotus runs one model call per reviewer, so the model choice is a cost
  decision — and it belongs to the consumer, not to this library. The retired
  pin also drifted silently: its comment said "latest model" while the value
  named an older one, and no test failed when that stopped being true.

  **What changes for you.** `review()` resolves the model highest-rung-first:
  an explicit `model=` kwarg → an explicitly passed `provider=`'s own
  configured model → the `ZENODOTUS_MODEL` environment variable → **a
  `ValueError` naming every one of those routes**. Previously the last rung was
  the built-in literal, so a call with none of the above silently ran
  `claude-opus-4-8`.

  **Migrating.** Pass `model="<model-id>"` to `review()`, or export
  `ZENODOTUS_MODEL`, or hand `review()` a pre-configured `provider=`. Callers
  who were happy with the old behaviour can restore it exactly with
  `ZENODOTUS_MODEL=claude-opus-4-8` — though [current model
  ids](https://platform.claude.com/docs/en/about-claude/models/overview) are
  worth a look first, since the old pin was already stale.

  **CLI users are affected too.** `zenodotus review` builds the default
  provider, so it now needs a model from `--model`, `ZENODOTUS_MODEL` or
  `cli.model` in `.zenodotus.json` (both added in this release, see *Added*).
  With none of them set the command prints the actionable message and exits
  **2** — "could not run", distinct from the existing exit 1, "ran, and the
  verdict blocks". The three-state pass/warn/block exit contract
  (`docs/PANEL_VERDICT_SPEC.md` §1) is unchanged for runs that actually
  execute. Erroring up front was chosen over inheriting an ambient model: the
  Anthropic SDK resolves credentials from the environment but never a model
  (`model` is required on every `messages.create` call), so there is nothing
  ambient to fall through to — and an unset model would otherwise surface as a
  confusing SDK-level failure on the first reviewer call.

### Fixed

- **Leak self-check scans tracked `dist/` and `build/`**
  ([#106](https://github.com/Kromatic-Innovation/zenodotus/issues/106)).
  The check had a private directory filter that the panel's file set did not
  have, so tracked files there were never scanned.
- **Leak self-check exempts a custom `--denylist-file`**
  ([#109](https://github.com/Kromatic-Innovation/zenodotus/issues/109)).
  Only the default denylist file name was exempt, so a custom one flagged
  itself.
- **The verdict marker's `git` call is guarded**
  ([#111](https://github.com/Kromatic-Innovation/zenodotus/issues/111)) like
  the other shell-out modules, so a missing `git` no longer raises.
- `resolve_policy()` documents that `reviewer_id` is for attribution only and
  the tool allowlist is panel-wide
  ([#82](https://github.com/Kromatic-Innovation/zenodotus/issues/82)).
- The docs no longer call `packaging_ok` pyroma-only, and no longer claim a
  package-metadata check that no code runs
  ([#113](https://github.com/Kromatic-Innovation/zenodotus/issues/113),
  [#115](https://github.com/Kromatic-Innovation/zenodotus/issues/115)).

## [0.3.0] - 2026-07-27

Minor release: reviewer tool isolation is now structurally enforced, not
prompt-instructed. Additive fields plus a default-posture change.

### Breaking-change status

**No API signature breaks for CLI/JSON consumers.** The `panel.Provider`
protocol itself gained a required keyword-only `tools` parameter on
`review()` — a custom `Provider` implementation that doesn't accept it will
raise `TypeError` when called by `panel.review()`. Update custom providers to
accept `*, tools: list[dict] | None = None`.

### Added

- **Structural tool isolation for the no-context reviewer panel**
  ([#79](https://github.com/Kromatic-Innovation/zenodotus/issues/79)). A new
  `zenodotus.isolation` module is the single enforcement point between "a
  provider wants to declare tool X" and "tool X reaches the API/agent call":
  - Deny by default — an unset or empty allowlist means a reviewer gets no
    tools at all, regardless of what a provider requests.
  - Explicit opt-in via `reviewer_tools` (`panel.review(..., reviewer_tools=
    {"reviewers": {"tools": [...]}})`) or the new CLI flag
    `--reviewer-tools tool1,tool2`.
  - Matching is exact-name-only — no wildcard, no category grant — so a
    tool-search/discovery capability is never implicitly admitted by
    allowlisting something else; it must be named explicitly, same as any
    other tool.
  - Every denied attempt is recorded, never swallowed, and surfaced in the run
    report (`--json` → `panel.isolation`, human mode → `isolation:` /
    `DENIED:` lines). `DeniedAttempt.at` is always a real ISO-8601 timestamp
    per `docs/PANEL_VERDICT_SPEC.md` §1.3 — `panel.review()` stamps it from
    the caller-supplied `at`, falling back to the current UTC time (same
    seconds-precision `Z`-suffixed shape the CLI already emits) when a
    library caller omits or passes an empty `at`.
- **`docs/PANEL_VERDICT_SPEC.md` bumped to 1.1** — new §1.3 "Isolation record"
  defines the shared `isolation.tools` / `isolation.denied` verdict shape,
  additive per §4, conformed to by both zenodotus and panelist.
- `PanelReview.isolation` and `ReviewerVerdict.tools` — the aggregate and
  per-reviewer effective tool sets, respectively.

## [0.2.0] - 2026-07-24

Minor release: the review gate's verdict is now three-state, a consumer-visible
capability change over the previous binary result. See
[docs/PANEL_VERDICT_SPEC.md](docs/PANEL_VERDICT_SPEC.md).

### Breaking-change status

**No API signature breaks.** There is, however, a behaviour change that the
version number alone cannot signal:

> **A review that previously exited non-zero may now exit `0`.**

Before `0.2.0` the gate was binary pass/fail, so any sufficiently serious
finding failed the run. From `0.2.0` the load-bearing invariant is that a CLI
exits `0` for **both** `pass` and `warn`, and non-zero **only** for `block`
(`docs/PANEL_VERDICT_SPEC.md` §1). Advisory findings no longer fail a gate.

If you use Zenodotus as a hard CI gate, this upgrade makes it **more
permissive**: findings that used to stop a pipeline now surface as warnings and
let it proceed. That is the intended design — but it is a relaxation, so review
what your pipeline expects before upgrading.

### Changed

- **Three-state review verdict.** The gate now returns one of `pass` / `warn` /
  `block`, replacing the previous binary pass/fail. Warnings are advisory and
  never block a release — only `block` fails the gate — so a reviewer can flag a
  concern without halting an otherwise-shippable candidate. (#31)
- **Reviews framed as pre-publish candidates.** The reviewer panel now evaluates
  a repo as an about-to-ship candidate rather than a live package, so expected
  pre-publish registry lag (the local version leading the registry) no longer
  produces a false block. (#53)

### Added

- **Durable cross-repo verdict marker.** A verdict recorded against an external
  repo now carries the reviewed commit SHA and the runner version, so a stored
  marker can be re-checked for staleness rather than trusted blindly. (#54)

## [0.1.1] - 2026-07-20

Initial packaging refinement of the bootstrap scaffold release.

## [0.1.0] - 2026-07-20

Initial bootstrap scaffold release: deterministic pre-gates plus the
no-context reviewer panel.

[0.4.0]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kromatic-Innovation/zenodotus/releases/tag/v0.1.0
