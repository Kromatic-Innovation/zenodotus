"""Zenodotus — OSS release-readiness gate.

Deterministic pre-gates (composed external tools) plus a no-context reviewer
panel that together judge whether a repository is ready to publish. See
docs/CONCEPT.md.
"""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    # `pyproject.toml` stays the single source of truth for the release version;
    # the installed distribution metadata is built from it, so there is no literal
    # to hand-sync and no way for the two to drift (issue #69).
    __version__ = _version("zenodotus")
except PackageNotFoundError:
    # Running from an uninstalled source tree. Use an unmistakable dev sentinel —
    # never a plausible release number like "0.0.0" that would read as a real
    # (broken) build if stamped into a durable cross-repo verdict marker (#54).
    __version__ = "0.0.0+unknown"
