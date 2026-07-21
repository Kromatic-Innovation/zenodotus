# Positioning

## One line
**Zenodotus is a no-context reviewer *panel* that reviews open-source releases — a three-state review gate (block / warn / pass) where warnings are advisory — not another readiness checklist.**

## The honest landscape
The deterministic side of "is this repo OSS-ready?" is a solved commodity. Free,
permissively-licensed tools already cover it well:

- **OpenSSF Scorecard** — security-supply-chain posture
- **REUSE / licensee** — license presence & compliance
- **Gitleaks** — leaked secrets
- **pyroma + twine check** — PyPI packaging hygiene
- **GitHub Community Standards** — README/CONTRIBUTING/CoC/SECURITY presence

Zenodotus does **not** reimplement these. It **composes them as a hard floor**
and never pretends the checklist is the hard part.

## Where the value is (the gap)
Checklists answer *"does artifact X exist and is it well-formed?"* They cannot
answer the questions that actually decide whether a release helps or embarrasses
you:

- Is the README coherent **to an outsider with zero internal context**?
- Is the naming/scope sensible — one thing done well, not a grab-bag?
- Is there **internal/proprietary leakage that isn't a "secret"** (internal
  hostnames, dead links, employee/competitor names, sarcastic comments)?
- Is this actually **useful and finished** enough to exist publicly?

These are judgment calls. Mature OSS orgs already gate on them — **with humans**,
not tools:

- **Google** — a mandatory open-source-release review by a dedicated team.
- **Apache Incubator** — a maturity self-assessment reviewed by the IPMC.
- **CNCF** — graduation requires an OpenSSF badge **plus** an independent audit.

The pattern is always **deterministic floor + human judgment ceiling.** Zenodotus's
novelty is operationalizing that ceiling as an **automatable, no-context,
multi-reviewer panel** — a niche with adjacent prior art (LLM-as-judge,
multi-agent PR review) but, as of this writing, no direct competitor aimed at
OSS *release-readiness* judgment.

## Why this framing matters for the build
- The README and any public messaging must **lead with the panel-as-gate**, and
  **explicitly credit the composed tools** for the deterministic floor. "Another
  OSS-readiness checklist" would be lost in a sea of them; the panel is the story.
- The value claim is only credible if the panel **demonstrably catches things the
  checklist misses.** That is the role of the `discovery_log`, and the public
  flip + publish were gated on it (docs/CONCEPT.md) — the bar was logged evidence
  + evals, not vibes. Today that evidence is carried publicly by the committed
  **eval suite** (`tests/evals/`, green in CI); the discovery log is the
  mechanism by which a longer public track record accumulates as panel runs land.

## Audience
Maintainers and orgs who publish open source and want a repeatable **review gate**
(block / warn / pass) that goes beyond linters — especially anyone already running
Scorecard/REUSE who feels the "is this actually ready for humans?" gap. It advises
by default (warnings never block) and can be tightened to block on genuine
blockers, so it earns trust as a reviewer before it ever gates a merge.

## Licensing
**Apache-2.0.** See the README and the `LICENSE` file.
