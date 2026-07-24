# Security Policy

## Supported Versions

Zenodotus is published to PyPI and pre-1.0, under active build-out (see
`docs/CONCEPT.md`). Until a tagged `1.0` release, security fixes target the latest
published release — the `main` branch it is cut from (via `promote-main.yml`) and
the corresponding PyPI release — plus the `develop` integration branch that feeds
it. Older releases and pre-release tags are not maintained.

| Version                      | Supported          |
| ---------------------------- | ------------------ |
| latest PyPI release / `main` | :white_check_mark: |
| `develop` (integration)      | :white_check_mark: |
| everything else              | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
pull requests, or discussions.**

Instead, report them privately using one of:

1. **GitHub private vulnerability reporting** (preferred) — open the repository's
   **Security** tab and choose **"Report a vulnerability"**. This opens a private
   advisory visible only to you and the maintainers.
2. **Email** — send details to **security@kromatic.com**.

Please include, as far as you can:

- a description of the issue and the potential impact,
- the affected file(s), version or commit, and configuration,
- step-by-step reproduction instructions or a proof of concept,
- any suggested remediation.

## What to Expect

- We aim to acknowledge a report within **3 business days**.
- We will keep you informed of progress toward a fix and coordinate a disclosure
  timeline with you.
- Please give us a reasonable opportunity to remediate before any public
  disclosure. We are happy to credit reporters who wish to be acknowledged.

Thank you for helping keep Zenodotus and its users safe.
