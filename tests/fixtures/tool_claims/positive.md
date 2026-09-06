# Positive fixture

Both of these tools have a real call site under `src/zenodotus/`, so naming
them here must not trip the guard.

The `pyroma` check is wired into the deterministic floor, and `gitleaks` is
run by the same floor to catch leaked secrets.
