# tickstamp

A tiny, dependency-free helper for formatting Unix timestamps as compact,
sortable strings. Give it an epoch seconds value and it returns a fixed-width
`YYYYMMDD-HHMMSS` stamp suitable for log lines, filenames, and sort keys — no
`datetime` formatting boilerplate, no third-party dependency.

Pure Python and standard-library only, so it installs in a second and imports
instantly.

## Install

```
pip install tickstamp
```

`tickstamp` supports Python 3.11 and newer. There are no runtime dependencies.

This README documents **0.3.0**, which adds the `utc` keyword for UTC-normalized
stamps (see Quickstart). If your installed copy formats in local time and ignores
`utc`, you are on an earlier release — upgrade with `pip install -U tickstamp`.

## Quickstart

```python
from tickstamp import stamp

stamp(1_700_000_000)            # "20231114-221320" (local time)
stamp(1_700_000_000, utc=True)  # "20231114-222000" (UTC, new in 0.3.0)
```

Every call returns a plain string; nothing mutates in place.

## Core operations

- `stamp(epoch)` — format epoch seconds as a local-time `YYYYMMDD-HHMMSS` string.
- `stamp(epoch, utc=True)` — format in UTC instead of local time (added in 0.3.0).

## Contributing

Contributions are welcome — see `CONTRIBUTING.md`. Keep the surface small and
dependency-free, and add a test for anything you change.

## License

`tickstamp` is released under the MIT License. See the `LICENSE` file for the
full text.
