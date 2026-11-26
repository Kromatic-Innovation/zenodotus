# Contributing

Zenodotus is public, published to PyPI, pre-1.0, and **in maintenance**: bug
and security fixes only, on a best-effort basis, with no new features planned
(see the Status section of README.md). Bug-fix and security-fix contributions
are welcome.

- Python >= 3.11. `pip install -e ".[dev]"`, `ruff check .`, `pytest`.
- The `discovery_log` module is load-bearing — do not weaken its schema without
  updating docs/CONCEPT.md and the prove-itself evals.
