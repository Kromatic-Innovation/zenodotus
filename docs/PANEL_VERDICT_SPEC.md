# Shared persona-panel verdict spec

**Status:** normative · **Version:** 1.0 · **Applies to:** any synthetic
reviewer/persona panel in the Kromatic org, in any language.

This document specifies a **shared verdict shape** — a three-state verdict
(`pass` / `warn` / `block`) plus a discovery-log record format — that
independent persona-panel implementations satisfy *by construction*, without
sharing code or taking a runtime dependency on one another.

Today two such implementations exist:

- **[panelist](https://github.com/Kromatic-Innovation/panelist)** — the org's
  general-purpose synthetic persona-panel engine (JS/npm). Domain: reader/buyer
  reaction, deal-killer cut-lists, drafting-aid pre-filtering.
- **zenodotus** (this repo) — an OSS release-readiness gate (Python/PyPI).
  Domain: no-context reviewer judgment on release-worthiness.

They are **separate implementations by deliberate decision**
([zenodotus#36](https://github.com/Kromatic-Innovation/zenodotus/issues/36),
2026-07-20): zenodotus's pitch is a lightweight `pip`/`pipx`-installable gate,
and making it shell out to a Node package at runtime would force every consumer
to install Node just to run a review — for a *conceptual* overlap ("ask an LLM
panel, get a verdict"), not shared code. The two panels serve different domains.

This spec is the chosen alternative to a runtime dependency: a common **verdict
vocabulary** both sides emit, so their outputs stay conceptually consistent and
**don't drift silently** — while their internals stay independent.

> **Non-goal.** This spec does NOT define personas, prompts, providers, context
> gathering, or how a verdict is *reached*. It constrains only the *shape of the
> result* a panel emits. Everything upstream of the verdict is each
> implementation's own concern.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used as in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## 1. The three-state verdict

A panel run resolves to exactly one of three **verdict states**:

| State   | Meaning                                                              | Exit code (for CLI implementations) |
| ------- | ------------------------------------------------------------------- | ----------------------------------- |
| `pass`  | No finding at or above the block threshold. Nothing to act on.      | `0`                                 |
| `warn`  | Advisory findings exist, but none is a blocker. Ship-able as-is.     | `0`                                 |
| `block` | At least one blocker finding (or an explicit reviewer no-go).        | non-zero                            |

Rules:

1. A conformant panel **MUST** report its aggregate result as exactly one of
   these three states.
2. **`warn` MUST NOT block.** A warning is advisory only. Any implementation
   that exposes an exit code **MUST** exit `0` for both `pass` and `warn`, and
   non-zero **only** for `block`. This is the load-bearing invariant: a gate
   that hard-blocks on advisory findings erodes trust
   ([zenodotus#31](https://github.com/Kromatic-Innovation/zenodotus/issues/31)).
3. **`block` is reserved for genuine blockers.** The default posture is
   advisory; blocking is the exception, not the norm.

### 1.1 Severity → state mapping

Individual findings carry a **severity**. The aggregate verdict is derived from
the most severe finding across the whole panel:

| Finding severity | Contributes to verdict state |
| ---------------- | ---------------------------- |
| `blocker`        | `block`                      |
| `major`          | `warn`                       |
| `minor`          | `warn`                       |
| *(no findings)*  | `pass`                       |

- A panel **MUST** use exactly the severity vocabulary `blocker` \| `major` \|
  `minor` on findings that appear in a conformant verdict.
- The aggregate state is the highest-ranked contribution: any `blocker` →
  `block`; else any `major`/`minor` → `warn`; else `pass`.
- An implementation **MAY** additionally let a reviewer return an explicit
  per-reviewer no-go that forces `block` even absent a `blocker`-severity
  finding (zenodotus does this today via each reviewer's `go` boolean). Such a
  no-go **MUST** be treated as equivalent to a `blocker` for the aggregate.

### 1.2 Verdict record shape

A conformant verdict is a JSON object with these fields:

```json
{
  "state": "pass | warn | block",
  "rationale": "one-line human-readable summary of the verdict",
  "findings": [
    {
      "finding":   "what the reviewer observed (required, non-empty)",
      "severity":  "blocker | major | minor",
      "category":  "implementation-defined category token (see §2)",
      "rationale": "why it matters (required, non-empty)",
      "reviewer":  "id of the reviewer that raised it (optional)"
    }
  ]
}
```

- `state`, `rationale`, and `findings` are **required**. `findings` **MUST** be
  present (an empty array when the state is `pass`).
- Each finding **MUST** carry a non-empty `finding`, a `severity` from the
  vocabulary above, a `category` token, and a non-empty `rationale`.
- `reviewer` is **RECOMMENDED** but not required at the verdict level — it is
  required in the discovery-log record (§2) so panel-only findings are
  attributable.
- Implementations **MAY** carry additional fields (e.g. per-reviewer verdicts,
  consensus details, provider metadata). Extra fields **MUST NOT** change the
  meaning of the fields above. A consumer **MUST** ignore fields it does not
  recognise.

> **zenodotus mapping (informative).** zenodotus currently emits a per-reviewer
> `go`/`no-go` boolean plus a `consensus_go` (see `src/zenodotus/panel.py`).
> The three-state projection is: `consensus_go == false` (a no-go or any
> `blocker`) → `block`; `consensus_go == true` with findings present → `warn`;
> clean → `pass`. Landing that projection in zenodotus's own CLI/verdict is
> tracked by **[zenodotus#31](https://github.com/Kromatic-Innovation/zenodotus/issues/31)**;
> this spec defines the target that work satisfies.

> **panelist mapping (informative).** panelist emits deal-killer cut-lists
> across a cross-model panel. A deal-killer maps to a `blocker` severity
> (→ `block`); a non-fatal reaction maps to `major`/`minor` (→ `warn`); a clean
> panel is `pass`. panelist's persona/schema internals are unaffected — only the
> emitted verdict envelope conforms.

---

## 2. Discovery-log format

The **discovery log** is the append-only record of panel findings — the
evidence base that a panel earns its keep by surfacing things deterministic
tooling could not (zenodotus: `docs/CONCEPT.md`, `src/zenodotus/discovery_log.py`).

- The log **MUST** be **JSONL**: one JSON object per line, append-only. Order is
  chronological-by-append; consumers **MUST NOT** assume any other ordering.
- Each line is one **discovery record**:

```json
{
  "repo":                    "artifact/repo under review (required)",
  "finding":                 "what was observed (required)",
  "category":                "one of the categories below (required)",
  "severity":                "blocker | major | minor (required)",
  "reviewer":                "id of the reviewer that raised it (required)",
  "rationale":               "why it matters (required)",
  "at":                      "ISO-8601 timestamp, caller-supplied (required)",
  "caught_by":               "panel (default)",
  "missed_by_deterministic": true,
  "tags":                    []
}
```

Rules:

1. Every field above except `tags` is **required** and **MUST** be non-empty
   (booleans excepted). `tags` defaults to `[]`.
2. **`at` MUST be caller-supplied**, not read from the clock inside the logging
   code. This keeps the log deterministic and testable — a hard requirement,
   not a nicety.
3. `caught_by` defaults to `"panel"`. A record for a panel finding **MUST** set
   `missed_by_deterministic: true` — the log's whole purpose is recording what
   the deterministic floor missed.
4. `severity` uses the same `blocker` \| `major` \| `minor` vocabulary as §1.1.
5. Serialisation **SHOULD** be stable (sorted keys) so appends are diff-friendly.

### 2.1 Category vocabulary

Categories are **domain-specific and implementation-defined** — the two panels
judge different things, so the spec does NOT pin a single closed category set.
A conformant implementation:

- **MUST** publish its own closed category set and validate findings against it.
- **MUST** include an `other` bucket for findings that fit no specific category.

zenodotus's category set (release-gate domain), for reference, is:

```
coherence · naming · scope · leakage · usefulness · doc-quality · other
```

panelist, judging reader/buyer reaction, publishes its own set (e.g. clarity,
value, trust, friction, …) — it is **not** required to adopt zenodotus's, and
zenodotus is not required to adopt panelist's. The **verdict states, the
severity vocabulary, and the discovery-record fields** are what the two share;
the category *tokens* are each panel's own.

---

## 3. Conformance

An implementation **conforms to this spec** when:

1. It emits an aggregate verdict of exactly `pass` \| `warn` \| `block` (§1),
   and — if it exposes an exit code — exits `0` for `pass`/`warn` and non-zero
   only for `block`.
2. Its findings use the `blocker` \| `major` \| `minor` severity vocabulary, and
   its aggregate state follows the §1.1 mapping.
3. Its verdict object carries at least the §1.2 required fields.
4. If it keeps a discovery log, the log is JSONL with the §2 record fields,
   caller-supplied `at`, and a published closed category set including `other`.

Conformance is **independent**: each implementation satisfies this spec in its
own language and codebase. There is **no shared library, no runtime dependency,
and no wire protocol between the two panels** — only this agreed shape.

---

## 4. Versioning

This spec is versioned (see the header). A change that would make a previously
conformant verdict non-conformant (renaming a state, removing a required field,
changing the severity→state mapping) is a **major** version bump. Additive,
backward-compatible changes (a new optional field, a clarifying rule) are a
**minor** bump. Each implementation **SHOULD** record which spec version it
targets.

## Changelog

- **1.0** ([zenodotus#36](https://github.com/Kromatic-Innovation/zenodotus/issues/36)) — initial spec: three-state `pass`/`warn`/`block`
  verdict, severity→state mapping, verdict record shape, and the JSONL
  discovery-log format. Derived from zenodotus's existing `panel.py` /
  `discovery_log.py` shapes and the three-state model of
  [zenodotus#31](https://github.com/Kromatic-Innovation/zenodotus/issues/31).
