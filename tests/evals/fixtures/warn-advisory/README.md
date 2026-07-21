# gridcalc

A small, dependency-free Python helper for evaluating rectangular grids of
numbers: build a `Grid` from nested lists, then take row/column sums, means, and
transposes with a compact, predictable API. It is meant for scripts and tests
where reaching for a full numerics stack is overkill but hand-rolling nested
loops over lists-of-lists gets tedious.

Everything is pure Python and standard-library only, so it installs in a second
and imports instantly.

## Install

```
pip install gridcalc
```

`gridcalc` supports Python 3.11 and newer. There are no runtime dependencies.

## Quickstart

```python
from gridcalc import Grid

g = Grid([[1, 2, 3],
          [4, 5, 6]])

g.row_sums()      # [6, 15]
g.col_sums()      # [5, 7, 9]
g.col_means()     # [2.5, 3.5, 4.5]
g.transpose()     # Grid([[1, 4], [2, 5], [3, 6]])
```

Every operation returns plain lists (or a new `Grid` for `transpose`); nothing
mutates in place.

## Core operations

- `row_sums()` / `col_sums()` — sum along each row or column.
- `row_means()` / `col_means()` — arithmetic mean along each row or column.
- `transpose()` — return a new `Grid` with rows and columns swapped.
- `flatten()` — return all cells as a single flat list, row-major.

## Contributing

Contributions are welcome — see `CONTRIBUTING.md`. Keep the surface small and
dependency-free, and add a test for anything you change.

## License

`gridcalc` is released under the MIT License. See the `LICENSE` file for the full
text.
