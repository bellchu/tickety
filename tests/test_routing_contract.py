import math
import unittest
from typing import get_args

from pydantic import ValidationError

from app.backend.ai_contracts import (
    ResolverGroup,
    ResolverRoutingAnalysis,
    RoutingRecommendation,
    TriageAnalysis,
)
class RoutingContractTests(unittest.TestCase):
    digest = "sha256:" + ("a" * 64)

    def recommendation(self, **overrides):
        payload = {
            "status": "ai_recommended",
            "domain": "enterprise_business_application",
            "candidates": [
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-1",
                    "rank": 1,
                    "score": 0.97,
                }
            ],
            "confidence_score": 0.97,
            "evidence_reason": "Provider taxonomy and ticket evidence agree.",
            "abstention_reason": None,
            "workspace_id": "workspace-1",
            "source_context_hash": self.digest,
            "catalog_version": "catalog-v1",
            "catalog_hash": self.digest,
            "policy_version": "policy-v1",
            "model_version": "model-v1",
        }
        payload.update(overrides)
        return payload

    def resolver_analysis(self, **overrides):
        payload = {
            "primary_group": "APPLICATION_OPERATIONS",
            "secondary_group": None,
            "confidence": 0.91,
            "scope": "multiple_users",
            "affected_service": "Billing platform",
            "failure_domain": "application processing failure",
            "reason": "Billing service rejects transactions after the interface delivers them.",
        }
        payload.update(overrides)
        return payload

    def test_accepts_catalog_bound_recommendation(self):
        result = RoutingRecommendation.model_validate(self.recommendation())

        self.assertEqual(result.candidates[0].group_id, "group-operations")
        self.assertEqual(result.candidates[0].workspace_id, result.workspace_id)

    def test_triage_contract_no_longer_selects_a_resolver(self):
        payload = {
            "sentiment": "Moderate",
            "category": "Software",
            "priority": "P2",
            "mood": "concerned",
            "action": "route",
            "reasoning": "scope: single user; application behavior blocks one requester",
        }
        result = TriageAnalysis.model_validate(payload)
        self.assertNotIn("recommended_team", result.model_dump())

        routine = TriageAnalysis.model_validate({
            **payload,
            "priority": "P4",
            "reasoning": "scope: single user; routine request with no current disruption",
        })
        self.assertEqual(routine.priority, "P4")

        with self.assertRaises(ValidationError):
            TriageAnalysis.model_validate({
                **payload,
                "recommended_team": "Application Support",
            })

    def test_resolver_contract_has_exact_fields_and_closed_group_set(self):
        self.assertEqual(
            set(ResolverRoutingAnalysis.model_fields),
            {
                "primary_group",
                "secondary_group",
                "confidence",
                "scope",
                "affected_service",
                "failure_domain",
                "reason",
            },
        )
        self.assertEqual(
            set(get_args(ResolverGroup)),
            {
                "SERVICE_DESK",
                "ENDPOINT_SUPPORT",
                "IDENTITY_ACCESS",
                "NETWORK_OPERATIONS",
                "INFRASTRUCTURE_OPERATIONS",
                "CLOUD_PLATFORM",
                "SECURITY_OPERATIONS",
                "BUSINESS_APPLICATIONS",
                "APPLICATION_OPERATIONS",
                "DATA_SERVICES",
                "INTEGRATION_SERVICES",
                "AUTOMATION_SERVICES",
                "SOFTWARE_ENGINEERING",
                "SERVICE_DELIVERY",
            },
        )
        for resolver_group in get_args(ResolverGroup):
            with self.subTest(resolver_group=resolver_group):
                result = ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(primary_group=resolver_group)
                )
                self.assertEqual(result.primary_group, resolver_group)

        for mutation in (
            {"primary_group": "APP_UNKNOWN"},
            {"invented_field": "ignored"},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(**mutation)
                )
        missing_secondary = self.resolver_analysis()
        missing_secondary.pop("secondary_group")
        with self.assertRaises(ValidationError):
            ResolverRoutingAnalysis.model_validate(missing_secondary)

    def test_secondary_group_is_distinct_evidence_not_a_helpdesk_fallback(self):
        valid = ResolverRoutingAnalysis.model_validate(
            self.resolver_analysis(secondary_group="INTEGRATION_SERVICES")
        )
        self.assertEqual(valid.secondary_group, "INTEGRATION_SERVICES")
        for secondary in ("APPLICATION_OPERATIONS", "SERVICE_DESK"):
            with self.subTest(secondary=secondary), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(secondary_group=secondary)
                )

    def test_confidence_is_finite_numeric_bounded_and_unknown_is_low_confidence(self):
        for invalid_confidence in (True, False, "0.8", math.nan, math.inf, -0.01, 1.01):
            with self.subTest(confidence=invalid_confidence), self.assertRaises(
                ValidationError
            ):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(confidence=invalid_confidence)
                )

        for unknown_field in ("affected_service", "failure_domain"):
            with self.subTest(field=unknown_field), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(**{unknown_field: "unknown", "confidence": 0.60})
                )
            valid = ResolverRoutingAnalysis.model_validate(
                self.resolver_analysis(**{unknown_field: "unknown", "confidence": 0.59})
            )
            self.assertEqual(valid.confidence, 0.59)

        negative_zero = ResolverRoutingAnalysis.model_validate(
            self.resolver_analysis(confidence=-0.0)
        )
        self.assertEqual(negative_zero.confidence, 0.0)
        self.assertEqual(
            math.copysign(1.0, negative_zero.confidence),
            1.0,
        )

    def test_routing_explanations_are_bounded_nonempty_single_lines(self):
        invalid_values = (
            {"affected_service": ""},
            {"affected_service": "Billing\nserver"},
            {"affected_service": "Billing\u2028server"},
            {"failure_domain": "network\rpath"},
            {"reason": "first line\nsecond line"},
            {"reason": "x" * 1_001},
        )
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(**values)
                )

    def test_unrouted_result_requires_reason_and_forbids_candidates(self):
        result = RoutingRecommendation.model_validate(
            self.recommendation(
                status="unrouted_review",
                candidates=[],
                confidence_score=0,
                abstention_reason="catalog_unavailable",
                catalog_version=None,
                catalog_hash=None,
                model_version=None,
            )
        )
        self.assertEqual(result.abstention_reason, "catalog_unavailable")

        with self.assertRaises(ValidationError):
            RoutingRecommendation.model_validate(
                self.recommendation(
                    status="unrouted_review",
                    abstention_reason="catalog_unavailable",
                )
            )

    def test_rejects_cross_workspace_duplicate_or_unordered_candidates(self):
        invalid_candidate_sets = (
            [
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-2",
                    "rank": 1,
                    "score": 0.9,
                }
            ],
            [
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-1",
                    "rank": 1,
                    "score": 0.9,
                },
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-1",
                    "rank": 2,
                    "score": 0.8,
                },
            ],
            [
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-1",
                    "rank": 2,
                    "score": 0.9,
                }
            ],
            [
                {
                    "group_id": "group-operations",
                    "workspace_id": "workspace-1",
                    "rank": 1,
                    "score": 0.7,
                },
                {
                    "group_id": "group-business-apps",
                    "workspace_id": "workspace-1",
                    "rank": 2,
                    "score": 0.8,
                },
            ],
        )

        for candidates in invalid_candidate_sets:
            with self.subTest(candidates=candidates), self.assertRaises(ValidationError):
                RoutingRecommendation.model_validate(
                    self.recommendation(candidates=candidates)
                )

    def test_rejects_missing_provenance_and_extra_fields(self):
        with self.assertRaises(ValidationError):
            RoutingRecommendation.model_validate(
                self.recommendation(catalog_hash=None)
            )
        with self.assertRaises(ValidationError):
            RoutingRecommendation.model_validate(
                self.recommendation(invented_group_name="Service Desk")
            )

if __name__ == "__main__":
    unittest.main()
