# tablekit

A tiny, dependency-free Python library for reading, filtering, and summarizing
small tabular datasets. `tablekit` does one thing well: it turns a list of rows
(dictionaries, or CSV text) into a lightweight `Table` you can slice, group, and
reduce with a small, predictable API — without pulling in a heavyweight
dataframe dependency for what is, most of the time, a few hundred rows.

It is meant for scripts, tests, and command-line tools where reaching for a full
dataframe stack is overkill, but hand-rolling `for` loops over lists of dicts
gets tedious and error-prone. Everything is pure Python and standard-library
only, so it installs in a second and imports instantly.

## Why tablekit

There is a real gap between "a list of dicts" and "a dataframe". Lists of dicts
are perfectly fine until you need to group by a column, compute a couple of
aggregates, and print the result as a readable table — at which point you are
writing the same fiddly plumbing for the third time this month. Dataframes solve
that, but they are a large dependency with their own type system, and they are
awkward to justify in a small utility or a test fixture.

`tablekit` sits deliberately in the middle:

- **Small surface.** One `Table` type and a handful of methods. You can read the
  whole public API in a few minutes.
- **No dependencies.** Standard library only. Nothing to audit, nothing to pin,
  nothing to break on a transitive upgrade.
- **Predictable.** Every operation returns a new `Table`; nothing mutates in
  place, so results are easy to reason about and safe to reuse.
- **Honest about scope.** It is for small data. It does not stream, it does not
  parallelize, and it holds everything in memory. If you have millions of rows,
  reach for a real dataframe — that is the right tool, and this one will tell you
  so rather than pretend otherwise.

## Install

```
pip install tablekit
```

`tablekit` supports Python 3.11 and newer. There are no runtime dependencies.

## Quickstart

```python
from tablekit import Table

rows = [
    {"team": "red", "points": 12, "player": "ana"},
    {"team": "red", "points": 9,  "player": "ben"},
    {"team": "blue", "points": 7, "player": "cat"},
    {"team": "blue", "points": 15, "player": "dot"},
]

table = Table(rows)

# Filter rows with a predicate.
strong = table.where(lambda r: r["points"] >= 10)

# Group by a column and reduce each group to a single number.
totals = table.group_by("team").aggregate("points", sum)

# Sort and take the top few.
leaders = table.sort_by("points", descending=True).head(2)

print(totals.to_rows())
# [{"team": "red", "points": 21}, {"team": "blue", "points": 22}]
```

Every method returns a new `Table`, so you can chain freely:

```python
result = (
    table
    .where(lambda r: r["points"] > 5)
    .group_by("team")
    .aggregate("points", max)
    .sort_by("points", descending=True)
)
```

## Reading data

You can build a `Table` from a list of dictionaries directly, or parse it from
CSV text:

```python
from tablekit import Table

# From rows.
t1 = Table([{"a": 1, "b": 2}, {"a": 3, "b": 4}])

# From CSV text (header row required).
csv = "a,b\n1,2\n3,4\n"
t2 = Table.from_csv(csv)
```

`from_csv` reads the header row for column names and parses the remaining lines.
Values are kept as strings unless you pass a `converters` mapping that turns a
column into another type:

```python
t = Table.from_csv(csv, converters={"a": int, "b": int})
```

Unknown columns in `converters` are ignored, and a column with no converter is
left as text. This keeps parsing forgiving: a malformed cell in a column you do
not care about will not crash a run that only touches other columns.

## Core operations

`tablekit` intentionally exposes a small, orthogonal set of operations. Each is
pure — it returns a new `Table` and never mutates the receiver.

### `where(predicate)`

Return a new table containing only the rows for which `predicate(row)` is truthy.

```python
adults = people.where(lambda r: r["age"] >= 18)
```

### `select(*columns)`

Return a new table with only the named columns, in the order given. Columns that
do not exist raise a `KeyError` so typos surface immediately rather than silently
producing empty output.

```python
slim = people.select("name", "age")
```

### `sort_by(column, descending=False)`

Return a new table sorted by one column. Sorting is stable, so ties preserve
their original order — useful when you sort by a secondary key first and a
primary key second.

```python
ranked = scores.sort_by("value", descending=True)
```

### `group_by(column)`

Return a `Grouping` keyed by the distinct values of `column`. A `Grouping` is not
itself a table; it is an intermediate you reduce with `aggregate`.

### `aggregate(column, reducer)`

Reduce each group to a single row, applying `reducer` (any callable taking a list
of values and returning one value — `sum`, `max`, `min`, `len`, or your own) to
the named column. The result is a `Table` with one row per group.

```python
totals = sales.group_by("region").aggregate("amount", sum)
```

### `head(n)` and `tail(n)`

Return the first or last `n` rows as a new table. Both clamp to the available
row count, so asking for more rows than exist simply returns all of them.

## Rendering

For quick inspection, `to_rows()` returns the plain list of dictionaries, and
`to_csv()` serializes back to CSV text with a header row:

```python
print(table.to_csv())
```

There is deliberately no built-in pretty-printer or color support: keeping the
output plain means it composes with whatever you already use to display text,
and it keeps the dependency footprint at exactly zero.

## Error handling

`tablekit` prefers loud, early failures over silent surprises:

- Selecting or sorting by a missing column raises `KeyError`.
- Building a `Table` from rows with inconsistent keys raises `ValueError`, naming
  the offending row — a ragged dataset is almost always a bug upstream, and it is
  cheaper to catch it here than three transformations later.
- `from_csv` on empty text returns an empty table rather than raising, so an
  optional input file that happens to be empty does not need special-casing.

## Testing

The suite is pure `pytest` and runs in well under a second:

```
pip install -e ".[dev]"
pytest -q
```

Every public method has direct tests, and the property that "operations never
mutate the receiver" is asserted explicitly, since it is the one invariant the
whole chaining model depends on.

## Contributing

Contributions are welcome — see `CONTRIBUTING.md` for the (short) process. In
brief: keep the surface small, keep it dependency-free, and add a test for
anything you change. Proposals that would grow `tablekit` toward a full dataframe
are, respectfully, out of scope; the value of this library is precisely that it
is not one.

## Design notes

A few decisions are worth spelling out, because they are the reason the library
stays small.

**Immutability everywhere.** Every operation returns a new `Table`. This costs a
little memory on large inputs, but for the small data `tablekit` targets it buys
a large simplification: there is no aliasing to reason about, results can be
cached and shared freely, and a chain of operations reads top-to-bottom like a
description of the transformation rather than a sequence of mutations.

**Predicates and reducers are plain callables.** `where` takes any function from
a row to a boolean, and `aggregate` takes any function from a list of values to
one value. There is no expression mini-language to learn and nothing to escape;
you use the Python you already know. The cost is that these operations are not
introspectable or serializable — an acceptable trade for a library whose whole
premise is that you are already writing Python around it.

**Strings by default on parse.** `from_csv` keeps values as text unless you ask
for a converter. CSV has no types, so inventing them silently is how subtle bugs
get in; making conversion explicit keeps the surprising cases visible.

## Frequently asked questions

**Can it read a file directly?** Not on its own — `from_csv` takes text, so you
call `Table.from_csv(path.read_text())`. Keeping I/O out of the library means it
never has to guess encodings or manage file handles, and it stays trivially
testable with in-memory strings.

**Does it handle nested data?** No. Rows are flat dictionaries of scalar values.
Nested structures are a different problem with different right answers, and
folding them in would double the surface area for a case most small datasets do
not have.

**Is it fast?** Fast enough for its target — a few thousand rows feel instant.
It is not optimized for large data and does not try to be; the honest answer for
millions of rows is to use a real dataframe library.

**Why not just use a dataframe?** If you already depend on one, do. `tablekit`
exists for the cases where you do not, and where adding one for a hundred rows
would be a heavier commitment than the task deserves.

## Versioning and stability

`tablekit` follows semantic versioning. The public API is the `Table` class and
its documented methods; anything prefixed with an underscore is internal and may
change without notice. Because the surface is intentionally small, breaking
changes should be rare — there is not much here to break.

## License

`tablekit` is released under the MIT License. See the `LICENSE` file for the full
text.
