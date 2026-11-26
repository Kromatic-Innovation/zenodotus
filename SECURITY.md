# Security Policy

## Supported Versions

Zenodotus is published to PyPI and pre-1.0, and is in maintenance: bug and
security fixes only, on a best-effort basis (see the Status section of
`README.md`). Security fixes target the latest
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

Instead, report them privately by **email** to **security@kromatic.com**.

If the repository's **Security** tab offers **"Report a vulnerability"** (GitHub
private vulnerability reporting), you may use that instead; it opens a private
advisory visible only to you and the maintainers.

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
