"""Record/replay layer for provider responses — deterministic panel evals in CI.

The reviewer panel is powered by an LLM, which makes it non-deterministic and
costly. For CI we want the panel to run **fully offline and reproducibly**, so we
record real provider responses once (against a committed fixture repo) and replay
them thereafter. This underpins the eval suite (repo issue #10, gating #5).

``CassetteProvider`` implements the same :class:`~zenodotus.panel.Provider`
protocol as ``AnthropicProvider``. Each interaction is keyed by a stable hash of
``(reviewer_id, gathered-context)`` — because the context is derived
deterministically from the repo's own files (relative paths, sorted tree), the
same fixture always produces the same key, so replays are exact.

    # CI / tests: replay only, no network, fail loud on a stale cassette
    provider = CassetteProvider("cassettes/x.json")            # mode="replay"

    # Refresh a cassette against the live API (run manually, needs a key):
    rec = CassetteProvider("cassettes/x.json", mode="record",
                           inner=AnthropicProvider())
    panel.review(fixture, provider=rec, ...)
    rec.save()
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CASSETTE_VERSION = 1


class CassetteMiss(KeyError):
    """Raised in replay mode when no recorded response matches the request."""


def interaction_key(reviewer_id: str, context: str) -> str:
    """Stable short hash identifying one (reviewer, context) interaction."""
    h = hashlib.sha256()
    h.update(reviewer_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(context.encode("utf-8"))
    return h.hexdigest()[:16]


class CassetteProvider:
    """A Provider that replays (or records) reviewer responses from a cassette file."""

    def __init__(self, path: str | Path, *, mode: str = "replay", inner=None):
        if mode not in ("replay", "record"):
            raise ValueError(f"unknown cassette mode: {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode requires an `inner` provider to record from")
        self.path = Path(path)
        self.mode = mode
        self.inner = inner
        self._data: dict[str, dict] = self._load(self.path) if mode == "replay" else {}

    @staticmethod
    def _load(path: Path) -> dict[str, dict]:
        if not path.exists():
            raise FileNotFoundError(f"cassette not found: {path}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        return dict(doc.get("interactions", {}))

    def review(self, reviewer_id: str, context: str) -> dict:
        key = interaction_key(reviewer_id, context)
        if self.mode == "replay":
            entry = self._data.get(key)
            if entry is None:
                raise CassetteMiss(
                    f"no recorded response for {reviewer_id} (key {key}) in {self.path.name}; "
                    "the cassette is stale — re-record it against the fixture."
                )
            return entry["response"]
        # record mode — make the real call, remember it
        response = self.inner.review(reviewer_id, context)
        self._data[key] = {"reviewer_id": reviewer_id, "response": response}
        return response

    def save(self) -> None:
        """Persist recorded interactions (record mode)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"version": CASSETTE_VERSION, "interactions": self._data}
        self.path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
