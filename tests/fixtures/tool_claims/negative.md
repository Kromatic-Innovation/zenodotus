# Negative fixture

This fixture names a tool with no call site anywhere in the codebase, using a
synthetic name (`flimflam`) so it can never be mistaken for a real claim.

The `flimflam` binary is invoked by the packaging gate to validate wheels
before they ship.
