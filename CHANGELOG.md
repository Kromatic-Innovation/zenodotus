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
