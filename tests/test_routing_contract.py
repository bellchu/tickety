import math
import os
import unittest
from typing import get_args
from unittest.mock import patch

from pydantic import ValidationError

from app.backend.ai_contracts import (
    ResolverGroup,
    ResolverRoutingAnalysis,
    RoutingRecommendation,
    TriageAnalysis,
)
from app.backend.routing_policy import routing_business_context


class RoutingContractTests(unittest.TestCase):
    digest = "sha256:" + ("a" * 64)

    def recommendation(self, **overrides):
        payload = {
            "status": "ai_recommended",
            "domain": "enterprise_business_application",
            "candidates": [
                {
                    "group_id": "group-wms",
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
            "primary_group": "APP_JDE",
            "secondary_group": None,
            "confidence": 0.91,
            "business_context": "JAM",
            "scope": "multiple_users",
            "affected_service": "JD Edwards",
            "failure_domain": "application processing failure",
            "reason": "JDE rejects transactions after the interface delivers them.",
        }
        payload.update(overrides)
        return payload

    def test_accepts_catalog_bound_recommendation(self):
        result = RoutingRecommendation.model_validate(self.recommendation())

        self.assertEqual(result.candidates[0].group_id, "group-wms")
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
                "business_context",
                "scope",
                "affected_service",
                "failure_domain",
                "reason",
            },
        )
        self.assertEqual(len(get_args(ResolverGroup)), 15)
        for resolver_group in get_args(ResolverGroup):
            with self.subTest(resolver_group=resolver_group):
                context = (
                    "ALMO" if resolver_group == "APP_CRM_ALMO"
                    else "JAM" if resolver_group == "APP_CRM_JAM"
                    else "JAM"
                )
                result = ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(
                        primary_group=resolver_group,
                        business_context=context,
                    )
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
            self.resolver_analysis(secondary_group="APP_EDI_API")
        )
        self.assertEqual(valid.secondary_group, "APP_EDI_API")
        for secondary in ("APP_JDE", "INFRA_HELPDESK"):
            with self.subTest(secondary=secondary), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(secondary_group=secondary)
                )

    def test_crm_groups_require_matching_business_context(self):
        valid_almo = ResolverRoutingAnalysis.model_validate(
            self.resolver_analysis(
                primary_group="APP_CRM_ALMO",
                business_context="ALMO",
            )
        )
        self.assertEqual(valid_almo.business_context, "ALMO")
        for values in (
            {"primary_group": "APP_CRM_ALMO", "business_context": "JAM"},
            {"primary_group": "APP_CRM_JAM", "business_context": "UNKNOWN"},
            {"secondary_group": "APP_CRM_ALMO", "business_context": "JAM"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ResolverRoutingAnalysis.model_validate(
                    self.resolver_analysis(**values)
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
            {"affected_service": "JDE\nserver"},
            {"affected_service": "JDE\u2028server"},
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
                    "group_id": "group-wms",
                    "workspace_id": "workspace-2",
                    "rank": 1,
                    "score": 0.9,
                }
            ],
            [
                {
                    "group_id": "group-wms",
                    "workspace_id": "workspace-1",
                    "rank": 1,
                    "score": 0.9,
                },
                {
                    "group_id": "group-wms",
                    "workspace_id": "workspace-1",
                    "rank": 2,
                    "score": 0.8,
                },
            ],
            [
                {
                    "group_id": "group-wms",
                    "workspace_id": "workspace-1",
                    "rank": 2,
                    "score": 0.9,
                }
            ],
            [
                {
                    "group_id": "group-wms",
                    "workspace_id": "workspace-1",
                    "rank": 1,
                    "score": 0.7,
                },
                {
                    "group_id": "group-erp",
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


class RoutingBusinessContextTests(unittest.TestCase):
    def test_context_uses_only_boundary_aware_allowlisted_domains(self):
        with patch.dict(
            os.environ,
            {
                "AI_ROUTING_ALMO_EMAIL_DOMAINS": "almo.example, legacy.almo.test",
                "AI_ROUTING_JAM_EMAIL_DOMAINS": "jam.example",
            },
        ):
            self.assertEqual(routing_business_context("user@almo.example"), "ALMO")
            self.assertEqual(
                routing_business_context("Requester <user@west.almo.example>"),
                "ALMO",
            )
            self.assertEqual(
                routing_business_context('"Doe, Jane" <USER@ALMO.EXAMPLE.>'),
                "ALMO",
            )
            self.assertEqual(routing_business_context("user@jam.example"), "JAM")
            self.assertEqual(
                routing_business_context("user@notalmo.example"), "UNKNOWN"
            )
            self.assertEqual(
                routing_business_context("user@jam.example.attacker.test"),
                "UNKNOWN",
            )

    def test_shared_malformed_arbitrary_and_conflicting_domains_fail_closed(self):
        with patch.dict(
            os.environ,
            {
                "AI_ROUTING_ALMO_EMAIL_DOMAINS": "nexora.com, conflict.example",
                "AI_ROUTING_JAM_EMAIL_DOMAINS": "conflict.example",
            },
        ):
            cases = (
                None,
                "",
                "not-an-email",
                "a@almo-keyword-only.example",
                "a@nexora.com",
                "a@sub.nexora.com",
                "a@conflict.example",
                "a@conflict.example,b@conflict.example",
            )
            for requester_email in cases:
                with self.subTest(requester_email=requester_email):
                    self.assertEqual(
                        routing_business_context(requester_email), "UNKNOWN"
                    )


if __name__ == "__main__":
    unittest.main()
