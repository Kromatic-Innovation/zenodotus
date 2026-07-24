# Changelog

All notable changes to Zenodotus are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-24

Minor release: the review gate's verdict is now three-state, a consumer-visible
capability change over the previous binary result. See
[docs/PANEL_VERDICT_SPEC.md](docs/PANEL_VERDICT_SPEC.md).

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
