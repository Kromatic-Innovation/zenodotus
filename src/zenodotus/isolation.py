"""Structural tool isolation for no-context reviewers (issue #79).

The panel's whole value is that each reviewer judges a release candidate the
way a stranger would. A reviewer that can reach an MCP server, web search, or
filesystem search is no longer a stranger — and the contamination is invisible
in the output, it still looks like a clean review. Telling a reviewer prompt
not to use tools is trust. Refusing to hand it any is structure.

This module is that structural gate. It is the ONLY place a provider's
requested tool declarations are checked against what a reviewer is actually
allowed to use — deny-by-default, explicit opt-in, and every denial recorded
rather than swallowed (docs/PANEL_VERDICT_SPEC.md §1.3).

Matching is by exact tool name only: no wildcard, no prefix match, no
category-based grant. That is what makes indirect acquisition impossible by
construction rather than by a maintained blocklist — a tool-search/discovery
capability is a tool like any other, so allowing something else never
implicitly admits it. It must be named on the allowlist itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Deny-by-default: an absent or empty allowlist means fully isolated.
DEFAULT_ALLOWED: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DeniedAttempt:
    """One tool a provider tried to declare that was not on the allowlist."""

    tool: str
    reviewer: str
    at: str

    def as_dict(self) -> dict:
        return {"tool": self.tool, "reviewer": self.reviewer, "at": self.at}


@dataclass
class ToolPolicy:
    """The resolved, effective tool policy for one reviewer.

    ``allowed`` is the explicit per-reviewer allowlist (empty by default).
    ``denied`` accumulates every tool declaration a provider tried to use that
    was not on the allowlist — nothing is ever dropped silently.
    """

    reviewer: str
    allowed: frozenset[str] = field(default_factory=lambda: DEFAULT_ALLOWED)
    denied: list[DeniedAttempt] = field(default_factory=list)

    def filter_tools(self, requested: list[dict] | None, at: str) -> list[dict]:
        """Return only the requested tool declarations present on the allowlist.

        ``requested`` is a list of tool declarations (each a dict with at
        least a ``name`` key) a provider wants to offer to the model. Anything
        not on ``self.allowed`` is dropped and recorded in ``self.denied``.
        """
        if not requested:
            return []
        permitted: list[dict] = []
        for decl in requested:
            name = decl.get("name", "")
            if name and name in self.allowed:
                permitted.append(decl)
            else:
                self.denied.append(
                    DeniedAttempt(tool=name, reviewer=self.reviewer, at=at)
                )
        return permitted


def resolve_allowed_tools(config: dict | list[str] | None) -> frozenset[str]:
    """Resolve the effective allowlist from config. Default: fully isolated.

    Accepts the shape the issue specifies::

        {"reviewers": {"tools": ["WebSearch"]}}

    or a pre-scoped ``{"tools": [...]}`` / bare list, for callers that already
    narrowed to the reviewers section. Absence of config, a missing ``tools``
    key, and an explicit ``[]`` are all equivalent to "fully isolated" — there
    is no separate "unset" state that defaults open.
    """
    if config is None:
        return DEFAULT_ALLOWED
    if isinstance(config, (list, tuple, set, frozenset)):
        return frozenset(config)
    if isinstance(config, dict):
        reviewers_cfg = config.get("reviewers", config)
        if isinstance(reviewers_cfg, dict):
            tools = reviewers_cfg.get("tools", [])
        else:
            tools = reviewers_cfg or []
        return frozenset(tools or [])
    return DEFAULT_ALLOWED


def resolve_policy(config: dict | list[str] | None, reviewer_id: str) -> ToolPolicy:
    """Build the effective :class:`ToolPolicy` for one reviewer from config."""
    return ToolPolicy(reviewer=reviewer_id, allowed=resolve_allowed_tools(config))
