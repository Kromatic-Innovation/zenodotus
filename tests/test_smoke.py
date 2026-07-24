"""Smoke tests for the package."""
from zenodotus import __version__
from zenodotus.discovery_log import Discovery, append, load


def test_version_is_real_or_dev_sentinel():
    """#69: __version__ is never the bare bootstrap placeholder.

    It is either the installed distribution version (which is built from — and so
    matches — pyproject.toml) or, from an uninstalled source tree, an unmistakable
    dev sentinel. Stronger than the old ``isinstance(..., str)`` guard, which the
    stale ``"0.0.0"`` placeholder satisfied.
    """
    from importlib.metadata import PackageNotFoundError, version

    assert isinstance(__version__, str)
    assert __version__ != "0.0.0"  # the retired bootstrap placeholder
    try:
        installed = version("zenodotus")
    except PackageNotFoundError:  # pragma: no cover - CI installs the package
        assert __version__ == "0.0.0+unknown"
    else:
        assert __version__ == installed


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
