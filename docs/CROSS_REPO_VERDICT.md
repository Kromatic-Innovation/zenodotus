# Cross-repo verdict marker

**Status:** normative · **Marker version:** `v1` · **Issue:**
[#54](https://github.com/Kromatic-Innovation/zenodotus/issues/54)

Zenodotus reviews not only itself but any external repo (`zenodotus review
<path-or-repo>`). This document specifies the **durable, machine-readable verdict
marker** it emits so a separate tool — hestia's `oss-status` command — can answer
"has zenodotus already cleared this repo's current `main` for publish?" without
any zenodotus-internal knowledge or state.

The design (approved 2026-07-21, issue #54) deliberately reuses primitives that
already exist — a GitHub comment plus an HTML-comment marker, mirroring the
`<!-- decision: ... -->` convention already used across the org. **No new state
file, service, or database.**

## 1. Format

The marker is a single HTML comment block:

```html
<!-- zenodotus-verdict: v1
     repo: <owner/name>
     sha: <full commit SHA the review ran against, or `unknown`>
     verdict: pass | warn | block
     ran_at: <ISO-8601 timestamp>
     runner: zenodotus vX.Y.Z
-->
```

- **`repo`** — the target repo slug (`owner/name`). Emitted from the reviewed
  tree's git `origin` remote, overridable with `--repo`.
- **`sha`** — the full commit SHA of the reviewed tree's git `HEAD`, or the
  sentinel `unknown` when the tree was not a git checkout (see §3).
- **`verdict`** — zenodotus's three-state verdict
  ([`docs/PANEL_VERDICT_SPEC.md`](PANEL_VERDICT_SPEC.md) §1): `pass` | `warn` |
  `block`. (The original design sketch used the older `pass`/`conditional`/`fail`
  words; the marker records the current vocabulary.)
- **`ran_at`** — when the review ran (ISO-8601, caller-supplied so it stays
  deterministic/testable).
- **`runner`** — the zenodotus version that produced the verdict.

## 2. Trigger & recording

- **Trigger: on-demand only.** The entry point is `zenodotus review <repo>
  --emit-verdict-marker`, on demand from a human or from hestia's
  `oss-status` command. No CI wiring is injected into the target repos:
  the tool stays generic and workspace-side tooling does not leak into it.
- **Recording: a GitHub comment on the target repo.** Zenodotus only *renders*
  the marker (`src/zenodotus/verdict_marker.py`) and emits it (in `--json` output
  and printed in human mode). **Posting** the comment is the caller's job — this
  keeps zenodotus dependency-free (no GitHub API, no tokens). GitHub's API is the
  store; there is no separate database.

## 3. Staleness

A verdict recorded against commit `X` is meaningless once the repo moves past
`X`. A consumer detects this **for free** from the marker's `sha`:

- Marker `sha` **==** target repo's current `main` HEAD → the verdict is
  **current**.
- Marker `sha` **!=** current HEAD, **or** `sha` is the `unknown` sentinel → the
  verdict is **stale**; surface it as "re-run", never as a valid clearance.

This satisfies the issue's explicit requirement that a consumer never silently
show a false "cleared" signal. Because `unknown` can never equal a real HEAD, a
verdict recorded against a non-git tree is always treated as stale.

## 4. Trust bar (advisory-only)

This ships **read-only/advisory**: hestia's `oss-status` surfaces the verdict as
one signal; nothing *gates* a publish on it (issue #54 out-of-scope). The blast
radius of "not enough cross-repo evidence yet" is therefore zero, which is why no
additional prove-itself milestone is required before emitting markers against
real repos.

## 5. Reference reader

`zenodotus.verdict_marker.parse_verdict_marker(text)` is a reference parser that
extracts a marker back into its fields (and returns `None` for an absent or
malformed marker — a partial marker must never read as a valid clearance). It
keeps the format honest and is available to any Python consumer; non-Python
consumers (hestia's `oss-status` is JS) implement the same trivial parse against
this spec.
