"""gridcalc — a tiny rectangular-grid calculator (pure standard library)."""
from __future__ import annotations


class Grid:
    """A rectangular grid of numbers backed by a list of equal-length rows."""

    def __init__(self, rows: list[list[float]]):
        if rows and len({len(r) for r in rows}) != 1:
            raise ValueError("all rows must have the same length")
        self.rows = [list(r) for r in rows]

    def row_sums(self) -> list[float]:
        return [sum(r) for r in self.rows]

    def col_sums(self) -> list[float]:
        return [sum(col) for col in zip(*self.rows)]

    def row_means(self) -> list[float]:
        return [sum(r) / len(r) for r in self.rows]

    def col_means(self) -> list[float]:
        return [sum(col) / len(col) for col in zip(*self.rows)]

    def transpose(self) -> "Grid":
        return Grid([list(col) for col in zip(*self.rows)])

    def flatten(self) -> list[float]:
        return [cell for row in self.rows for cell in row]
