"""tickstamp — format Unix timestamps as compact, sortable strings (stdlib only)."""
from __future__ import annotations

from datetime import datetime, timezone

_FMT = "%Y%m%d-%H%M%S"


def stamp(epoch: float, *, utc: bool = False) -> str:
    """Format ``epoch`` seconds as a ``YYYYMMDD-HHMMSS`` string.

    Local time by default; pass ``utc=True`` for a UTC-normalized stamp
    (added in 0.3.0).
    """
    tz = timezone.utc if utc else None
    return datetime.fromtimestamp(epoch, tz=tz).strftime(_FMT)
