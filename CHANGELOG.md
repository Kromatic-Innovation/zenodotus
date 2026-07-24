# Changelog

All notable changes to `zenodotus` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning convention

`zenodotus` is **pre-1.0 (0.x)**. MAJOR is reserved for the 1.0 stability
commitment and stays unused, so MINOR and PATCH do double duty:

- **PATCH** (`0.x.Y` → `0.x.Y+1`) — no consumer-visible behaviour change:
  dependency bumps, CI-only fixes, docs, internal refactors. This is the default.
- **MINOR** (`0.x.Y` → `0.x+1.0`) — any consumer-visible *addition*, **or** any
  *breaking* change. Because MAJOR is off-limits pre-1.0, a breaking change still
  lands as MINOR — so **every MINOR entry states explicitly whether it breaks
  anything**, rather than leaving the version number to imply it.

## [0.2.0] - 2026-07-24

First release of the **three-state review gate**. This is a MINOR bump: it adds
consumer-visible capability and changes observable gate behaviour.

### Breaking-change status

**No API signature breaks.** But there *is* a behaviour change consumers must
know about, called out here because the version number alone does not signal it:

> A review that previously exited **non-zero** may now exit **`0`**.

Pre-`0.2.0` the gate was binary pass/fail, so any sufficiently serious finding
failed the run. From `0.2.0` the verdict is three-state, and the load-bearing
invariant is that a CLI exits `0` for **both** `pass` and `warn`, and non-zero
**only** for `block`. Advisory findings therefore no longer fail a gate.

If you rely on zenodotus as a hard CI gate, this makes it **more permissive**:
findings that used to stop a pipeline now surface as warnings and let it
proceed. That is the intended design (see `docs/PANEL_VERDICT_SPEC.md` §1), but
review your pipeline's expectations before upgrading.

### Added

- **Three-state review-gate verdict** (`pass` / `warn` / `block`) replacing the
  binary pass/fail model, with warnings advisory by design and never blocking
  (#31). Specified in `docs/PANEL_VERDICT_SPEC.md`; test coverage spans all
  three states plus the exit-code contract, including a WARN eval.
- **Durable cross-repo verdict marker** (#54) — records a review verdict into an
  external repo so a later consumer can tell whether the verdict still applies.
  Pins the reviewed commit SHA, and records an explicit `unknown` sentinel when
  the reviewed tree is not a git checkout, so a stale verdict can never read as
  a false "cleared". Documented in `docs/CROSS_REPO_VERDICT.md`.

### Fixed

- **Reviews are framed as pre-publish candidates** (#53), so the gate personas no
  longer treat expected pre-publish registry lag as a blocker. Previously a
  package legitimately not yet on its registry could be failed for it — a false
  positive precisely when the gate is most likely to run.

### Changed

- Repositioned the docs around the three-state gate, making the advisory nature
  of warnings explicit.
- Genericised org-name references in public-facing docs and CI (#19, #55).

### Chore

- Pinned `ruff==0.16.0` and applied its 11 auto-fixes (#62). `ruff` had been
  declared unbounded, so a new release could turn CI red with no code change —
  the failure mode that took a sibling repo's CI down on 2026-07-24.
- Adopted the canonical Internal Platform `promote-main.yml`.
- Gitignored the generated `.agents/` and `.codex/` directories (#57).

### Known issue

`src/zenodotus/__init__.py` still carries the bootstrap placeholder
`__version__ = "0.0.0"`. `runner_string()` prefers installed distribution
metadata, so an installed package stamps the correct version and **consumers are
unaffected**; the placeholder only surfaces when running from an uninstalled
source tree. Tracked separately.

## [0.1.1] and earlier

Released before this changelog existed. See the
[git tags](https://github.com/Kromatic-Innovation/zenodotus/tags) and their
commit ranges for what shipped.

[0.2.0]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Kromatic-Innovation/zenodotus/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kromatic-Innovation/zenodotus/releases/tag/v0.1.0
