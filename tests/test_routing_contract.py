import unittest

from pydantic import ValidationError

from app.backend.ai_contracts import RoutingRecommendation


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

    def test_accepts_catalog_bound_recommendation(self):
        result = RoutingRecommendation.model_validate(self.recommendation())

        self.assertEqual(result.candidates[0].group_id, "group-wms")
        self.assertEqual(result.candidates[0].workspace_id, result.workspace_id)

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


if __name__ == "__main__":
    unittest.main()
