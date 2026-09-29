# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Resource identities and the ``within`` constraint (NTA-2, phase 1).

A resource pattern is only as safe as the comparison behind it. These tests
pin the forms that are refused rather than normalised: a resource that could
mean two things is not authorised as either.
"""
from __future__ import annotations

import pytest

from remora.capabilities.constraints import Condition, ToolConstraint, evaluate_constraint
from remora.capabilities.model import CapabilityRefusal
from remora.capabilities.resource import (
    ResourceRefused,
    canonical_resource,
    canonical_resource_pattern,
    resource_within,
)


class TestCanonicalResource:
    @pytest.mark.parametrize("raw, expected", [
        ("workspace://reports/september.pdf", "workspace://reports/september.pdf"),
        ("Workspace://Reports-EU/x", "workspace://reports-eu/x"),
        ("https://Billing.Example:8443/api/invoice", "https://billing.example:8443/api/invoice"),
        ("workspace://reports/", "workspace://reports"),
        ("database://reporting-eu", "database://reporting-eu"),
    ])
    def test_the_canonical_form(self, raw, expected):
        assert canonical_resource(raw) == expected

    def test_the_path_keeps_its_case(self):
        assert canonical_resource("workspace://reports/September.pdf").endswith("/September.pdf")

    @pytest.mark.parametrize("raw", [
        "workspace://reports/../secrets/key",
        "workspace://reports/./x",
        "workspace://reports//x",
        "workspace://reports/%2e%2e/secrets",
        "workspace://reports/x%2Fy",
        "workspace://reports\\..\\secrets",
        "workspace://reports/x y",
        "workspace://reports/x\x00",
        "workspace://user@reports/x",
        "https://billing.example/api?to=evil",
        "https://billing.example/api#frag",
        "reports/september.pdf",
        "workspace:reports/x",
        "://reports/x",
        "",
        "workspace://",
        "1ws://reports/x",
    ])
    def test_ambiguous_forms_are_refused(self, raw):
        with pytest.raises(ResourceRefused):
            canonical_resource(raw)

    def test_a_non_string_is_refused(self):
        with pytest.raises(ResourceRefused):
            canonical_resource(None)  # type: ignore[arg-type]


class TestPatterns:
    def test_a_subtree_pattern(self):
        assert canonical_resource_pattern("Workspace://reports/*") == "workspace://reports/*"

    @pytest.mark.parametrize("raw", ["*", "workspace://*", "workspace://reports/*/x",
                                     "workspace://re*", "workspace://reports/**"])
    def test_wildcards_only_close_a_subtree(self, raw):
        with pytest.raises(ResourceRefused):
            canonical_resource_pattern(raw)


class TestWithin:
    @pytest.mark.parametrize("resource, pattern, inside", [
        ("workspace://reports/september.pdf", "workspace://reports/*", True),
        ("workspace://reports/2026/09.pdf", "workspace://reports/*", True),
        ("workspace://reports", "workspace://reports/*", False),
        ("workspace://reports-secret/x", "workspace://reports/*", False),
        ("workspace://reportsx", "workspace://reports/*", False),
        ("secrets://production/key", "workspace://reports/*", False),
        ("workspace://reports/september.pdf", "workspace://reports/september.pdf", True),
        ("workspace://reports/september.pdf.bak", "workspace://reports/september.pdf", False),
        ("database://billing-us/monthly", "database://reporting-eu/*", False),
    ])
    def test_membership_respects_segment_boundaries(self, resource, pattern, inside):
        assert resource_within(resource, [pattern]) is inside

    def test_an_ambiguous_resource_is_never_within(self):
        assert resource_within("workspace://reports/../secrets", ["workspace://reports/*"]) is False


class TestTheWithinCondition:
    def _constraint(self):
        return ToolConstraint.from_dict({"conditions": [
            {"argument": "resource", "within": ["workspace://reports/*"]}]})

    def test_a_resource_inside_the_pattern_passes(self):
        assert evaluate_constraint(self._constraint(),
                                   {"resource": "workspace://reports/a.pdf"}) is None

    def test_a_resource_outside_refuses_as_resource_not_authorized(self):
        assert evaluate_constraint(self._constraint(), {"resource": "secrets://production/k"}) is (
            CapabilityRefusal.RESOURCE_NOT_AUTHORIZED)

    def test_traversal_refuses_as_resource_not_authorized(self):
        assert evaluate_constraint(self._constraint(),
                                   {"resource": "workspace://reports/../secrets/k"}) is (
            CapabilityRefusal.RESOURCE_NOT_AUTHORIZED)

    def test_the_patterns_are_validated_when_the_policy_is_read(self):
        with pytest.raises(ValueError):
            Condition.from_dict({"argument": "resource", "within": ["workspace://re*"]})

    def test_the_canonical_form_round_trips(self):
        c = self._constraint()
        assert ToolConstraint.from_dict(c.canonical()) == c
