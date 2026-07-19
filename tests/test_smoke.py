"""Smoke tests for the bootstrap scaffold."""
from zenodotus import __version__
from zenodotus.discovery_log import Discovery, append, load


def test_version():
    assert isinstance(__version__, str)


def test_discovery_log_roundtrip(tmp_path):
    log = tmp_path / "discoveries.jsonl"
    d = Discovery(
        repo="example/repo",
        finding="README assumes internal context an outsider can't follow",
        category="coherence",
        severity="major",
        reviewer="reviewer-1",
        rationale="References an internal dashboard with no explanation",
        at="2026-01-01T00:00:00Z",
    )
    append(log, d)
    rows = load(log)
    assert len(rows) == 1
    assert rows[0]["missed_by_deterministic"] is True
    assert rows[0]["category"] == "coherence"


def test_discovery_rejects_unknown_category():
    import pytest

    with pytest.raises(ValueError):
        Discovery(
            repo="r", finding="f", category="not-a-category", severity="minor",
            reviewer="x", rationale="y", at="2026-01-01T00:00:00Z",
        )
