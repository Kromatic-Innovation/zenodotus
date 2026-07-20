# Contributing to tablekit

Thanks for your interest. `tablekit` is deliberately small, so the process is
short.

1. Open an issue describing the change before a large PR, so we can agree it fits
   the scope (small, dependency-free, tabular helpers — not a dataframe).
2. Add or update tests for anything you change. `pytest -q` must pass.
3. Keep the public API minimal. A new method needs a clear, common use case that
   the existing operations cannot already express by chaining.
4. No runtime dependencies. Standard library only.

By contributing you agree that your work is released under the project's MIT
License.
