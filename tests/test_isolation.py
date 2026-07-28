"""Unit tests for the reviewer tool-isolation seam (issue #79).

These test `zenodotus.isolation` directly and in isolation from `panel.py` —
the exported unit itself, not just the panel wiring. See test_panel.py for the
integration-level assertions (denial surfaced in PanelReview, per-reviewer
tools recorded, etc).
"""

from __future__ import annotations

from zenodotus import isolation

# --- resolve_allowed_tools ---------------------------------------------------- #


def test_no_config_is_fully_isolated():
    assert isolation.resolve_allowed_tools(None) == frozenset()


def test_empty_config_is_fully_isolated():
    assert isolation.resolve_allowed_tools({}) == frozenset()


def test_explicit_empty_tools_list_is_fully_isolated():
    assert isolation.resolve_allowed_tools({"reviewers": {"tools": []}}) == frozenset()


def test_explicit_allowlist_is_honored():
    cfg = {"reviewers": {"tools": ["WebSearch", "recall"]}}
    assert isolation.resolve_allowed_tools(cfg) == frozenset({"WebSearch", "recall"})


def test_prescoped_dict_accepted():
    assert isolation.resolve_allowed_tools({"tools": ["recall"]}) == frozenset(
        {"recall"}
    )


def test_bare_list_accepted():
    assert isolation.resolve_allowed_tools(["recall"]) == frozenset({"recall"})


# --- resolve_policy ------------------------------------------------------------ #


def test_resolve_policy_default_is_empty_allowlist():
    policy = isolation.resolve_policy(None, "reviewer-1")
    assert policy.reviewer == "reviewer-1"
    assert policy.allowed == frozenset()
    assert policy.denied == []


def test_resolve_policy_honors_explicit_allowlist():
    policy = isolation.resolve_policy(
        {"reviewers": {"tools": ["recall"]}}, "reviewer-1"
    )
    assert policy.allowed == frozenset({"recall"})


# --- ToolPolicy.filter_tools ---------------------------------------------------- #


def test_filter_tools_default_denies_everything():
    policy = isolation.resolve_policy(None, "reviewer-1")
    permitted = policy.filter_tools([{"name": "recall"}], at="2026-07-27T00:00:00Z")
    assert permitted == []
    assert len(policy.denied) == 1
    assert policy.denied[0] == isolation.DeniedAttempt(
        tool="recall", reviewer="reviewer-1", at="2026-07-27T00:00:00Z"
    )


def test_filter_tools_permits_only_explicit_allowlist_entries():
    policy = isolation.ToolPolicy(reviewer="reviewer-1", allowed=frozenset({"recall"}))
    permitted = policy.filter_tools(
        [{"name": "recall"}, {"name": "WebSearch"}], at="2026-07-27T00:00:00Z"
    )
    assert permitted == [{"name": "recall"}]
    assert [d.tool for d in policy.denied] == ["WebSearch"]


def test_filter_tools_no_requested_tools_is_a_noop():
    policy = isolation.ToolPolicy(reviewer="reviewer-1", allowed=frozenset({"recall"}))
    assert policy.filter_tools(None, at="2026-07-27T00:00:00Z") == []
    assert policy.filter_tools([], at="2026-07-27T00:00:00Z") == []
    assert policy.denied == []


def test_discovery_capability_denied_by_the_same_generic_mechanism():
    # No blocklist of "discovery-sounding" names exists — a tool-search /
    # tool-discovery capability is denied by the exact same exact-name-match
    # rule as any other tool. Allowing an unrelated tool must not admit it.
    policy = isolation.ToolPolicy(reviewer="reviewer-1", allowed=frozenset({"recall"}))
    permitted = policy.filter_tools(
        [{"name": "tool_search"}], at="2026-07-27T00:00:00Z"
    )
    assert permitted == []
    assert policy.denied[0].tool == "tool_search"


def test_unnamed_tool_declaration_is_denied_not_silently_dropped():
    policy = isolation.ToolPolicy(reviewer="reviewer-1")
    permitted = policy.filter_tools([{}], at="2026-07-27T00:00:00Z")
    assert permitted == []
    assert len(policy.denied) == 1
    assert policy.denied[0].tool == ""


def test_denied_attempt_as_dict():
    d = isolation.DeniedAttempt(
        tool="recall", reviewer="reviewer-1", at="2026-07-27T00:00:00Z"
    )
    assert d.as_dict() == {
        "tool": "recall",
        "reviewer": "reviewer-1",
        "at": "2026-07-27T00:00:00Z",
    }
