# Contributing

Zenodotus is public and published to PyPI (0.1.0), pre-1.0 and under active
build-out (see issues) — contributions are welcome. The "prove itself" work
(docs/CONCEPT.md) continues as ongoing validation that the reviewer panel earns
its keep; it is no longer a gate holding the repo private.

- Python >= 3.11. `pip install -e ".[dev]"`, `ruff check .`, `pytest`.
- The `discovery_log` module is load-bearing — do not weaken its schema without
  updating docs/CONCEPT.md and the prove-itself evals.
