# Contributing

Zenodotus is a bootstrap scaffold under active build-out (see issues). Until it
reaches its "prove itself" milestone (docs/CONCEPT.md) it stays private.

- Python >= 3.11. `pip install -e ".[dev]"`, `ruff check .`, `pytest`.
- The `discovery_log` module is load-bearing — do not weaken its schema without
  updating docs/CONCEPT.md and the prove-itself evals.
