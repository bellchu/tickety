import hashlib
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main, resolver_catalog
from app.backend.database import (
    AIArtifactRecord,
    AgentResolverTeamMappingRecord,
    Base,
    DirectoryPersonExternalIdentityRecord,
    DirectoryPersonLocalAccountRecord,
    DirectoryPersonRecord,
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
    get_db,
)
from app.backend.database import TicketRecord
from app.backend.schema import (
    AgentTeamMappingRecommendationResponse,
    ResolverCatalogRecommendationResponse,
)


class ResolverCatalogRecommendationTests(unittest.TestCase):
    pipeline_version = "route-policy-v1"
    model = "provider/model-v1"

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 8, 26, 12, 0, 0)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _input_hash(ticket: TicketRecord) -> str:
        return hashlib.sha256(
            f"{ticket.subject}|{ticket.description}".encode("utf-8")
        ).hexdigest()

    def _add_group(
        self,
        db,
        *,
        record_id: str,
        external_id: str,
        name: str,
        binding_id: str = "binding-1",
        provider: str = "freshservice",
        workspace_id: str = "workspace-1",
    ) -> ExternalGroupRecord:
        group = ExternalGroupRecord(
            id=record_id,
            binding_id=binding_id,
            provider=provider,
            external_id=external_id,
            workspace_id=workspace_id,
            name=name,
            active=True,
        )
        db.add(group)
        return group

    def _add_agent(
        self,
        db,
        *,
        record_id: str,
        external_id: str,
        groups: list[ExternalGroupRecord],
        secret_name: str,
        binding_id: str = "binding-1",
        provider: str = "freshservice",
    ) -> ExternalUserRecord:
        agent = ExternalUserRecord(
            id=record_id,
            binding_id=binding_id,
            provider=provider,
            external_id=external_id,
            user_type="agent",
            name=secret_name,
            active=True,
        )
        db.add(agent)
        db.flush()
        for group in groups:
            db.add(ExternalGroupMembershipRecord(
                external_group_id=group.id,
                external_user_id=agent.id,
                membership_kind="member",
            ))
        return agent

    def _add_ticket(
        self,
        db,
        *,
        index: int,
        agent: ExternalUserRecord,
        direct_group_id: str | None,
        resolver_code: str = "APPLICATION_OPERATIONS",
        binding_id: str = "binding-1",
        provider: str = "freshservice",
        workspace_id: str = "workspace-1",
    ) -> TicketRecord:
        ticket = TicketRecord(
            id=f"ticket-{binding_id}-{workspace_id}-{resolver_code}-{index}",
            subject=f"Current assignment observation {index}",
            description="Validated current assignment evidence",
            reporter="requester@example.invalid",
            status="Open",
            binding_id=binding_id,
            external_source=provider,
            external_assignee_id=agent.external_id,
            external_group_id=direct_group_id,
            external_workspace_id=workspace_id,
            external_updated_at=self.now - timedelta(days=index),
            ai_suggested_team=resolver_code,
            ai_secondary_team=None,
            ai_routing_confidence=0.91,
            ai_routing_scope="multiple_users",
            ai_affected_service="Billing platform",
            ai_failure_domain="application processing failure",
            ai_routing_reason="Billing service rejected a delivered transaction.",
        )
        ticket.ai_routing_input_hash = self._input_hash(ticket)
        db.add(ticket)
        db.flush()
        payload = resolver_catalog._routing_payload(ticket)
        db.add(AIArtifactRecord(
            ticket_id=ticket.id,
            artifact="route",
            input_hash=ticket.ai_routing_input_hash,
            pipeline_version=self.pipeline_version,
            provider="test-provider",
            model=self.model,
            synthetic=False,
            content_hash=resolver_catalog._routing_content_hash(payload),
            active=True,
        ))
        return ticket

    def _recommend(self, db, *, history_limit=resolver_catalog.HISTORY_TICKET_LIMIT):
        result = resolver_catalog.recommend_resolver_catalog_mappings(
            db,
            generated_at=self.now,
            pipeline_version=self.pipeline_version,
            model=self.model,
            allow_synthetic=False,
            input_hash_for_ticket=self._input_hash,
            history_limit=history_limit,
        )
        return ResolverCatalogRecommendationResponse.model_validate(result).model_dump()

    def _recommend_agents(self, db, *, window_days=30):
        result = resolver_catalog.recommend_agent_team_mappings(
            db,
            generated_at=self.now,
            pipeline_version=self.pipeline_version,
            model=self.model,
            allow_synthetic=False,
            input_hash_for_ticket=self._input_hash,
            window_days=window_days,
        )
        return AgentTeamMappingRecommendationResponse.model_validate(
            result
        ).model_dump()

    def test_recommends_agent_team_from_trusted_routed_history_without_writing(self):
        with self.session_factory() as db:
            local_user = UserRecord(
                id="local-agent",
                name="Local Agent",
                role="agent",
                is_active=True,
            )
            db.add(local_user)
            person = DirectoryPersonRecord(id="person-agent", state="active")
            db.add(person)
            db.flush()
            db.add(DirectoryPersonLocalAccountRecord(
                person_id=person.id,
                user_id=local_user.id,
            ))
            external_agent = self._add_agent(
                db,
                record_id="external-agent-record",
                external_id="external-agent-7",
                groups=[],
                secret_name="Provider Agent Seven",
            )
            db.add(DirectoryPersonExternalIdentityRecord(
                person_id=person.id,
                external_user_id=external_agent.id,
                link_method="manual",
                link_state="active",
            ))
            for index in range(5):
                self._add_ticket(
                    db,
                    index=index,
                    agent=external_agent,
                    direct_group_id=None,
                    resolver_code="APPLICATION_OPERATIONS",
                )
            self._add_ticket(
                db,
                index=31,
                agent=external_agent,
                direct_group_id=None,
                resolver_code="SOFTWARE_ENGINEERING",
            )
            db.commit()

            payload = self._recommend_agents(db)
            expanded_payload = self._recommend_agents(db, window_days=60)
            persisted_mappings = db.query(
                AgentResolverTeamMappingRecord
            ).count()

        self.assertTrue(payload["ready"])
        self.assertFalse(payload["mapping_applied"])
        self.assertEqual(persisted_mappings, 0)
        recommendation = payload["recommendations"][0]
        self.assertEqual(recommendation["subject_key"], "person:person-agent")
        self.assertEqual(recommendation["person_id"], "person-agent")
        self.assertEqual(recommendation["user_id"], "local-agent")
        self.assertEqual(recommendation["resolver_group"], "APPLICATION_OPERATIONS")
        self.assertEqual(recommendation["evidence_ticket_count"], 5)
        self.assertEqual(recommendation["total_trusted_ticket_count"], 5)
        self.assertEqual(payload["window_days"], 30)
        self.assertEqual(payload["coverage"]["candidate_ticket_count"], 5)
        self.assertEqual(payload["coverage"]["attributed_ticket_count"], 5)
        self.assertEqual(expanded_payload["window_days"], 60)
        self.assertEqual(expanded_payload["coverage"]["candidate_ticket_count"], 6)
        self.assertEqual(
            expanded_payload["recommendations"][0]["total_trusted_ticket_count"],
            6,
        )

    def test_agent_recommender_abstains_on_split_history(self):
        with self.session_factory() as db:
            db.add(UserRecord(
                id="split-agent",
                name="Split Agent",
                role="agent",
                is_active=True,
            ))
            external_agent = self._add_agent(
                db,
                record_id="split-external-record",
                external_id="split-external-agent",
                groups=[],
                secret_name="Split Provider Agent",
            )
            db.add(UserExternalIdentityLinkRecord(
                user_id="split-agent",
                external_user_id=external_agent.id,
                binding_id=external_agent.binding_id,
                provider=external_agent.provider,
            ))
            for index, resolver_code in enumerate(
                ["APPLICATION_OPERATIONS", "APPLICATION_OPERATIONS", "SOFTWARE_ENGINEERING", "SOFTWARE_ENGINEERING"]
            ):
                self._add_ticket(
                    db,
                    index=index,
                    agent=external_agent,
                    direct_group_id=None,
                    resolver_code=resolver_code,
                )
            db.commit()
            payload = self._recommend_agents(db)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["recommendations"], [])
        self.assertEqual(payload["coverage"]["analyzed_subject_count"], 1)
        self.assertEqual(payload["coverage"]["attributed_ticket_count"], 4)

    def test_recommends_exact_catalog_group_from_current_assignment_observations(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="internal-group-1",
                external_id="provider-group-100",
                name="Application Operations",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"private-agent-record-{number}",
                    external_id=f"private-agent-external-{number}",
                    groups=[group],
                    secret_name=f"Private Agent Name {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                ticket = self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=group.external_id,
                )
            db.commit()

            payload = self._recommend(db)

        recommendation = next(
            item for item in payload["recommendations"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(recommendation["provider_group_id"], "provider-group-100")
        self.assertEqual(recommendation["provider_group_name"], "Application Operations")
        self.assertEqual(recommendation["evidence_ticket_count"], 10)
        self.assertEqual(recommendation["direct_assignment_ticket_count"], 10)
        self.assertEqual(recommendation["distinct_agent_count"], 2)
        self.assertEqual(recommendation["group_share"], 1.0)
        self.assertLess(recommendation["confidence"], recommendation["group_share"])
        self.assertTrue(payload["advisory_only"])
        self.assertFalse(payload["mapping_applied"])
        self.assertTrue(payload["no_mapping_applied"])
        self.assertEqual(payload["coverage"]["trusted_route_ticket_count"], 10)
        self.assertEqual(payload["coverage"]["unambiguous_ticket_count"], 10)
        serialized = json.dumps(payload, default=str)
        self.assertNotIn("Private Agent Name", serialized)
        self.assertNotIn("private-agent-record", serialized)
        self.assertNotIn("private-agent-external", serialized)

    def test_agent_membership_placeholder_group_is_never_recommended(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="placeholder-group-record",
                external_id="placeholder-provider-group",
                name="Group placeholder-provider-group",
            )
            group.profile_json = (
                resolver_catalog.AGENT_MEMBERSHIP_PLACEHOLDER_PROFILE_JSON
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"placeholder-agent-{number}",
                    external_id=f"placeholder-external-agent-{number}",
                    groups=[group],
                    secret_name=f"Placeholder Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=group.external_id,
                )
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        self.assertEqual(payload["coverage"]["trusted_route_ticket_count"], 10)
        self.assertEqual(
            payload["coverage"]["membership_eligible_ticket_count"], 0
        )
        gap = next(
            item for item in payload["scoped_gaps"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(gap["reason"], "no_unambiguous_membership_evidence")
        serialized = json.dumps(payload, default=str)
        self.assertNotIn("placeholder-provider-group", serialized)
        self.assertNotIn("Group placeholder-provider-group", serialized)

    def test_multi_group_agent_casts_only_direct_vote_and_never_fans_out(self):
        with self.session_factory() as db:
            first = self._add_group(
                db,
                record_id="internal-group-a",
                external_id="provider-group-a",
                name="Primary Resolver Group",
            )
            second = self._add_group(
                db,
                record_id="internal-group-b",
                external_id="provider-group-b",
                name="Secondary Resolver Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"agent-{number}",
                    external_id=f"external-agent-{number}",
                    groups=[first, second],
                    secret_name=f"Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=first.external_id,
                )
            db.commit()

            payload = self._recommend(db)

        recommendation = next(
            item for item in payload["recommendations"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(recommendation["provider_group_id"], first.external_id)
        self.assertEqual(recommendation["unambiguous_ticket_count"], 10)
        self.assertEqual(recommendation["candidate_group_count"], 1)
        self.assertEqual(recommendation["ambiguous_membership_ticket_count"], 0)

    def test_recommendations_never_mix_binding_provider_or_workspace_scopes(self):
        with self.session_factory() as db:
            expected = {}
            for scope_number in range(2):
                binding_id = f"binding-{scope_number}"
                provider = f"provider-{scope_number}"
                workspace_id = f"workspace-{scope_number}"
                group = self._add_group(
                    db,
                    record_id=f"scoped-group-{scope_number}",
                    external_id=f"scoped-provider-group-{scope_number}",
                    name=f"Scoped Group {scope_number}",
                    binding_id=binding_id,
                    provider=provider,
                    workspace_id=workspace_id,
                )
                agents = [
                    self._add_agent(
                        db,
                        record_id=f"scoped-agent-{scope_number}-{agent_number}",
                        external_id=f"scoped-external-{scope_number}-{agent_number}",
                        groups=[group],
                        secret_name=f"Scoped Agent {scope_number}-{agent_number}",
                        binding_id=binding_id,
                        provider=provider,
                    )
                    for agent_number in range(2)
                ]
                for index in range(10):
                    self._add_ticket(
                        db,
                        index=index,
                        agent=agents[index % 2],
                        direct_group_id=group.external_id,
                        binding_id=binding_id,
                        provider=provider,
                        workspace_id=workspace_id,
                    )
                expected[(binding_id, provider, workspace_id)] = group.external_id
            db.commit()

            payload = self._recommend(db)

        recommendations = [
            item for item in payload["recommendations"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        ]
        self.assertEqual(len(recommendations), 2)
        for item in recommendations:
            scope = item["scope"]
            scope_key = (
                scope["binding_id"],
                scope["provider"],
                scope["workspace_id"],
            )
            self.assertEqual(item["provider_group_id"], expected[scope_key])
            self.assertEqual(item["trusted_ticket_count"], 10)

    def test_unique_membership_is_used_only_when_ticket_group_is_blank(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="sole-membership-group",
                external_id="sole-membership-provider-group",
                name="Sole Membership Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"sole-agent-{number}",
                    external_id=f"sole-external-{number}",
                    groups=[group],
                    secret_name=f"Sole Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=None,
                )
            db.commit()

            payload = self._recommend(db)

        recommendation = next(
            item for item in payload["recommendations"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(recommendation["direct_assignment_ticket_count"], 0)
        self.assertEqual(recommendation["sole_membership_ticket_count"], 10)
        self.assertIn("0 direct group assignments", recommendation["reason"])
        self.assertIn("10 unique-membership inferences", recommendation["reason"])

    def test_nonblank_conflicting_ticket_group_never_uses_sole_membership(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="conflict-membership-group",
                external_id="conflict-membership-provider-group",
                name="Conflicting Membership Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"conflict-agent-{number}",
                    external_id=f"conflict-external-{number}",
                    groups=[group],
                    secret_name=f"Conflict Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id="different-explicit-provider-group",
                )
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        gap = next(
            item for item in payload["scoped_gaps"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(gap["reason"], "no_unambiguous_membership_evidence")
        self.assertEqual(gap["ambiguous_membership_ticket_count"], 10)

    def test_ambiguous_memberships_abstain_without_exposing_candidate_groups(self):
        with self.session_factory() as db:
            groups = [
                self._add_group(
                    db,
                    record_id=f"hidden-group-{number}",
                    external_id=f"hidden-provider-group-{number}",
                    name=f"Hidden Candidate {number}",
                )
                for number in range(2)
            ]
            agents = [
                self._add_agent(
                    db,
                    record_id=f"ambiguous-agent-{number}",
                    external_id=f"ambiguous-external-{number}",
                    groups=groups,
                    secret_name=f"Ambiguous Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id="not-a-catalog-membership",
                )
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        gap = next(
            item for item in payload["scoped_gaps"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(gap["reason"], "no_unambiguous_membership_evidence")
        self.assertEqual(gap["ambiguous_membership_ticket_count"], 10)
        serialized_gap = json.dumps(gap)
        self.assertNotIn("hidden-provider-group", serialized_gap)
        self.assertNotIn("Hidden Candidate", serialized_gap)

    def test_stale_recomputed_input_hash_fails_closed(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="group-stale",
                external_id="provider-group-stale",
                name="Stale Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"stale-agent-{number}",
                    external_id=f"stale-external-{number}",
                    groups=[group],
                    secret_name=f"Stale Agent {number}",
                )
                for number in range(2)
            ]
            tickets = [
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=group.external_id,
                )
                for index in range(10)
            ]
            tickets[0].description = "Ticket text changed after routing"
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        self.assertEqual(payload["coverage"]["candidate_ticket_count"], 10)
        self.assertEqual(payload["coverage"]["trusted_route_ticket_count"], 9)

    def test_window_uses_only_bounded_provider_timestamps(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="group-old-provider-update",
                external_id="provider-group-old-provider-update",
                name="Old Provider Assignment Group",
            )
            agent = self._add_agent(
                db,
                record_id="old-provider-agent",
                external_id="old-provider-external-agent",
                groups=[group],
                secret_name="Old Provider Agent",
            )
            ticket = self._add_ticket(
                db,
                index=1,
                agent=agent,
                direct_group_id=group.external_id,
            )
            ticket.status = "Open"
            ticket.external_updated_at = self.now - timedelta(days=400)
            ticket.updated_at = self.now
            future_ticket = self._add_ticket(
                db,
                index=2,
                agent=agent,
                direct_group_id=group.external_id,
            )
            future_ticket.external_updated_at = self.now + timedelta(days=1)
            db.commit()

            payload = self._recommend(db)

        self.assertEqual(payload["coverage"]["candidate_ticket_count"], 0)
        self.assertEqual(payload["coverage"]["trusted_route_ticket_count"], 0)
        self.assertFalse(payload["recommendations"])

    def test_weak_single_agent_sample_abstains(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="group-single-agent",
                external_id="provider-group-single-agent",
                name="Single Agent Group",
            )
            agent = self._add_agent(
                db,
                record_id="only-agent-record",
                external_id="only-agent-external",
                groups=[group],
                secret_name="Only Agent",
            )
            for index in range(10):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agent,
                    direct_group_id=group.external_id,
                )
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        gap = next(
            item for item in payload["scoped_gaps"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(gap["reason"], "insufficient_agent_diversity")

    def test_raw_share_boundary_abstains_when_wilson_confidence_is_low(self):
        with self.session_factory() as db:
            leading_group = self._add_group(
                db,
                record_id="wilson-leading-group",
                external_id="wilson-leading-provider-group",
                name="Wilson Leading Group",
            )
            runner_group = self._add_group(
                db,
                record_id="wilson-runner-group",
                external_id="wilson-runner-provider-group",
                name="Wilson Runner Group",
            )
            leading_agents = [
                self._add_agent(
                    db,
                    record_id=f"wilson-leading-agent-{number}",
                    external_id=f"wilson-leading-external-{number}",
                    groups=[leading_group],
                    secret_name=f"Wilson Leading Agent {number}",
                )
                for number in range(2)
            ]
            runner_agents = [
                self._add_agent(
                    db,
                    record_id=f"wilson-runner-agent-{number}",
                    external_id=f"wilson-runner-external-{number}",
                    groups=[runner_group],
                    secret_name=f"Wilson Runner Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(12):
                self._add_ticket(
                    db,
                    index=index,
                    agent=leading_agents[index % 2],
                    direct_group_id=leading_group.external_id,
                )
            for offset in range(8):
                self._add_ticket(
                    db,
                    index=100 + offset,
                    agent=runner_agents[offset % 2],
                    direct_group_id=runner_group.external_id,
                )
            db.commit()

            payload = self._recommend(db)

        self.assertFalse(payload["recommendations"])
        gap = next(
            item for item in payload["scoped_gaps"]
            if item["resolver_code"] == "APPLICATION_OPERATIONS"
        )
        self.assertEqual(gap["leading_ticket_count"], 12)
        self.assertEqual(gap["reason"], "low_sample_adjusted_confidence")
        self.assertEqual(payload["thresholds"]["minimum_confidence"], 0.55)

    def test_evidence_limit_is_enforced_and_disclosed(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="group-bounded",
                external_id="provider-group-bounded",
                name="Bounded Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"bounded-agent-{number}",
                    external_id=f"bounded-external-{number}",
                    groups=[group],
                    secret_name=f"Bounded Agent {number}",
                )
                for number in range(2)
            ]
            for index in range(12):
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=group.external_id,
                )
            db.commit()

            payload = self._recommend(db, history_limit=10)

        self.assertEqual(payload["coverage"]["candidate_ticket_count"], 10)
        self.assertEqual(payload["coverage"]["analyzed_ticket_count"], 10)
        self.assertTrue(payload["coverage"]["history_truncated"])
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["recommendations"])
        self.assertTrue(all(
            gap["reason"] == "evidence_truncated"
            for gap in payload["scoped_gaps"]
        ))

    def test_duplicate_active_route_artifacts_fail_closed(self):
        with self.session_factory() as db:
            group = self._add_group(
                db,
                record_id="group-duplicate-artifact",
                external_id="provider-group-duplicate-artifact",
                name="Duplicate Artifact Group",
            )
            agents = [
                self._add_agent(
                    db,
                    record_id=f"duplicate-agent-{number}",
                    external_id=f"duplicate-external-{number}",
                    groups=[group],
                    secret_name=f"Duplicate Agent {number}",
                )
                for number in range(2)
            ]
            tickets = [
                self._add_ticket(
                    db,
                    index=index,
                    agent=agents[index % 2],
                    direct_group_id=group.external_id,
                )
                for index in range(10)
            ]
            duplicate_ticket = tickets[0]
            duplicate_payload = resolver_catalog._routing_payload(duplicate_ticket)
            db.add(AIArtifactRecord(
                ticket_id=duplicate_ticket.id,
                artifact="route",
                input_hash=duplicate_ticket.ai_routing_input_hash,
                pipeline_version=self.pipeline_version,
                provider="test-provider",
                model=self.model,
                synthetic=False,
                content_hash=resolver_catalog._routing_content_hash(duplicate_payload),
                active=True,
            ))
            db.commit()

            payload = self._recommend(db)

        self.assertEqual(payload["coverage"]["trusted_route_ticket_count"], 9)
        self.assertFalse(payload["recommendations"])

    def test_empty_catalog_marks_every_resolver_code_unmapped(self):
        with self.session_factory() as db:
            payload = self._recommend(db)

        self.assertFalse(payload["ready"])
        self.assertFalse(payload["scopes"])
        self.assertFalse(payload["recommendations"])
        self.assertIsNone(payload["unmapped_codes_scope"])
        self.assertEqual(
            set(payload["unmapped_codes"]),
            set(resolver_catalog.AI_RESOLVER_TEAMS),
        )

    def test_confidence_is_sample_adjusted_and_never_exceeds_share(self):
        ten = resolver_catalog.wilson_lower_bound(10, 10)
        hundred = resolver_catalog.wilson_lower_bound(100, 100)

        self.assertGreater(hundred, ten)
        self.assertLessEqual(ten, 1.0)
        self.assertLessEqual(hundred, 1.0)
        self.assertLessEqual(resolver_catalog.wilson_lower_bound(6, 10), 0.6)

    def test_content_hash_matches_existing_persistence_helper(self):
        payload = {
            "primary_group": "APPLICATION_OPERATIONS",
            "secondary_group": None,
            "confidence": 0.91,
            "scope": "multiple_users",
            "affected_service": "Billing platform – Montréal",
            "failure_domain": "application processing failure",
            "reason": "Billing service rejected a delivered transaction.",
        }

        self.assertEqual(
            resolver_catalog._routing_content_hash(payload),
            main._routing_payload_content_hash(payload),
        )


class ResolverCatalogEndpointAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add_all([
                UserRecord(id="admin", name="Admin", role="admin", is_active=True),
                UserRecord(
                    id="supervisor",
                    name="Supervisor",
                    role="supervisor",
                    is_active=True,
                ),
                UserRecord(id="agent", name="Agent", role="agent", is_active=True),
            ])
            db.commit()

        def override_db():
            with self.session_factory() as db:
                yield db

        main.app.dependency_overrides[get_db] = override_db
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.middleware_roles_patch = patch.object(
            main,
            "_roles_required_for_request",
            return_value=None,
        )
        self.middleware_roles_patch.start()
        self.demo_patch = patch.object(
            main.settings_module,
            "is_production_mode",
            return_value=False,
        )
        self.demo_patch.start()
        self.reserve_patch = patch.object(main, "_reserve_analytics_request")
        self.reserve_mock = self.reserve_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.reserve_patch.stop()
        self.demo_patch.stop()
        self.middleware_roles_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _as_role(self, role: str):
        def current_user():
            with self.session_factory() as db:
                return db.get(UserRecord, role)

        main.app.dependency_overrides[main.get_protected_ai_user] = current_user

    def test_agent_is_forbidden_and_supervisor_get_is_read_only(self):
        self._as_role("agent")
        forbidden = self.client.get("/admin/routing-catalog/recommendations")
        self.assertEqual(forbidden.status_code, 403)
        agent_mapping_forbidden = self.client.get(
            "/admin/agent-team-mapping-recommendations"
        )
        self.assertEqual(agent_mapping_forbidden.status_code, 403)

        self._as_role("supervisor")
        response = self.client.get("/admin/routing-catalog/recommendations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertTrue(response.json()["advisory_only"])
        self.assertFalse(response.json()["mapping_applied"])
        self.assertTrue(response.json()["no_mapping_applied"])
        mapping_response = self.client.get(
            "/admin/agent-team-mapping-recommendations"
        )
        self.assertEqual(mapping_response.status_code, 200)
        self.assertEqual(
            mapping_response.headers["cache-control"], "private, no-store"
        )
        self.assertTrue(mapping_response.json()["advisory_only"])
        self.assertFalse(mapping_response.json()["mapping_applied"])
        self.assertEqual(mapping_response.json()["recommendations"], [])
        supervisor_override = self.client.get(
            "/admin/agent-team-mapping-recommendations?window_days=60"
        )
        self.assertEqual(supervisor_override.status_code, 403)

        self._as_role("admin")
        admin_override = self.client.get(
            "/admin/agent-team-mapping-recommendations?window_days=60"
        )
        self.assertEqual(admin_override.status_code, 200)
        self.assertEqual(admin_override.json()["window_days"], 60)
        self.assertEqual(self.reserve_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
