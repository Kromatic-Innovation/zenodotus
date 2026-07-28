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
    the caller-supplied `at`, falling back to the current UTC time when a
    library caller omits both `log_path` and `at`.
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

[0.2.0]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kromatic-Innovation/zenodotus/releases/tag/v0.1.0
