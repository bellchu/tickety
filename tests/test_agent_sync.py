import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    ExternalConversationRecord,
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    TicketRecord,
    UserRecord,
)
from app.backend.integrations import sync
from app.backend.schema import ExternalTicket


class _Adapter:
    provider_name = "jira"


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        UserRecord.__table__.create(self.engine)
        ExternalUserRecord.__table__.create(self.engine)
        ExternalGroupRecord.__table__.create(self.engine)
        ExternalGroupMembershipRecord.__table__.create(self.engine)
        TicketRecord.__table__.create(self.engine)
        ExternalConversationRecord.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(UserRecord(
                id="existing-user",
                name="Existing Alice",
                email="alice@example.com",
            ))
            db.commit()

        self.external_agent = {
            "accountId": "jira-alice",
            "displayName": "Provider Alice",
            "emailAddress": "alice@example.com",
            "active": True,
        }

    def tearDown(self):
        self.engine.dispose()

    def _sync(self):
        with patch.object(sync, "SessionLocal", self.session_factory):
            return sync._import_external_users(
                _Adapter(),
                [self.external_agent],
            )

    def test_remote_email_match_never_links_or_changes_tickety_user(self):
        result = self._sync()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).count(), 1)
            local_user = db.query(UserRecord).one()
            self.assertEqual(local_user.name, "Existing Alice")
            remote_user = db.query(ExternalUserRecord).one()
            self.assertEqual(remote_user.name, "Provider Alice")
            self.assertEqual(remote_user.email, local_user.email)

    def test_remote_refresh_updates_only_external_directory(self):
        self._sync()
        self.external_agent["displayName"] = "Provider Alice Updated"
        result = self._sync()

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).one().name, "Existing Alice")
            self.assertEqual(
                db.query(ExternalUserRecord).one().name,
                "Provider Alice Updated",
            )

    def test_ticket_sync_never_promotes_external_assignee_to_local_owner(self):
        with self.session_factory() as db:
            action, ticket = sync._upsert_ticket(
                db,
                ExternalTicket(
                    external_id="JIRA-1",
                    subject="Provider ticket",
                    description="Provider-owned description",
                    reporter="requester@example.com",
                    priority="P3",
                    status="Open",
                    assignee_id="existing-user",
                ),
                "jira",
                overwrite=True,
            )
            self.assertEqual(action, "new")
            self.assertEqual(ticket.external_assignee_id, "existing-user")
            self.assertIsNone(ticket.assignee_id)

    def test_missing_provider_identity_is_deactivated_without_touching_local_user(self):
        self._sync()
        with patch.object(sync, "SessionLocal", self.session_factory):
            result = sync._import_external_users(_Adapter(), [])

        self.assertEqual(result["deactivated"], 1)
        with self.session_factory() as db:
            self.assertFalse(db.query(ExternalUserRecord).one().active)
            self.assertTrue(db.query(UserRecord).one().is_active)

    def test_invalid_provider_identity_does_not_rollback_valid_users(self):
        valid_second_agent = {
            "accountId": "jira-bob",
            "displayName": "Provider Bob",
            "emailAddress": "bob@example.com",
            "active": True,
        }
        with patch.object(sync, "SessionLocal", self.session_factory):
            result = sync._import_external_users(
                _Adapter(),
                [self.external_agent, {"displayName": "Missing ID"}, valid_second_agent],
            )

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(
            result["error_details"],
            ["external_user_processing_failed:ValueError"],
        )
        with self.session_factory() as db:
            self.assertEqual(
                {row.external_id for row in db.query(ExternalUserRecord).all()},
                {"jira-alice", "jira-bob"},
            )

    def test_requester_fetch_failure_preserves_requesters_and_imports_agents(self):
        with self.session_factory() as db:
            db.add(ExternalUserRecord(
                id="existing-requester",
                binding_id="legacy",
                provider="freshservice",
                external_id="requester-1",
                user_type="requester",
                name="Existing Requester",
                active=True,
            ))
            db.commit()

        request = httpx.Request(
            "GET", "https://readonly.freshservice.com/api/v2/requesters"
        )
        response = httpx.Response(403, request=request)
        adapter = MagicMock()
        adapter.provider_name = "freshservice"
        adapter.fetch_agents = AsyncMock(return_value=[{
            "id": "agent-1",
            "first_name": "Provider",
            "last_name": "Agent",
            "active": True,
        }])
        adapter.fetch_requesters = AsyncMock(side_effect=httpx.HTTPStatusError(
            "requester access denied", request=request, response=response
        ))
        adapter.fetch_groups = AsyncMock(return_value=[])

        with patch.object(sync, "SessionLocal", self.session_factory):
            result = asyncio.run(sync.async_sync_external_users(adapter))

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(
            result["error_details"],
            ["external_requester_fetch_failed:http_status_403"],
        )
        with self.session_factory() as db:
            requester = db.get(ExternalUserRecord, "existing-requester")
            self.assertTrue(requester.active)
            agent = db.query(ExternalUserRecord).filter(
                ExternalUserRecord.external_id == "agent-1"
            ).one()
            self.assertEqual(agent.name, "Provider Agent")

    def test_failed_agent_partition_is_not_authoritative_for_deactivation(self):
        with self.session_factory() as db:
            db.add(ExternalUserRecord(
                id="existing-agent",
                binding_id="legacy",
                provider="freshservice",
                external_id="agent-existing",
                user_type="agent",
                name="Existing Agent",
                active=True,
            ))
            db.commit()

        request = httpx.Request(
            "GET", "https://readonly.freshservice.com/api/v2/agents"
        )
        response = httpx.Response(401, request=request)
        adapter = MagicMock()
        adapter.provider_name = "freshservice"
        adapter.fetch_agents = AsyncMock(side_effect=httpx.HTTPStatusError(
            "agent authentication failed", request=request, response=response
        ))
        adapter.fetch_requesters = AsyncMock(return_value=[])
        adapter.fetch_groups = AsyncMock(return_value=[])

        with patch.object(sync, "SessionLocal", self.session_factory):
            result = asyncio.run(sync.async_sync_external_users(adapter))

        self.assertEqual(result["errors"], 1)
        self.assertEqual(
            result["error_details"],
            ["external_agent_fetch_failed:http_status_401"],
        )
        with self.session_factory() as db:
            self.assertTrue(db.get(ExternalUserRecord, "existing-agent").active)

    def test_suspended_provider_code_is_reported_without_response_body(self):
        request = httpx.Request(
            "GET", "https://readonly.freshservice.com/api/v2/agents"
        )
        response = httpx.Response(
            403,
            request=request,
            json={"code": "account_suspended", "description": "private detail"},
        )
        detail = sync._external_user_fetch_error_detail(
            "agent",
            httpx.HTTPStatusError(
                "account unavailable", request=request, response=response
            ),
        )

        self.assertEqual(
            detail,
            "external_agent_fetch_failed:account_suspended",
        )
        self.assertNotIn("private detail", detail)

    def test_provider_groups_and_member_relationships_are_projected(self):
        self.external_agent["member_of"] = ["service-desk"]
        self._sync()
        groups = [{
            "id": "service-desk",
            "name": "Service Desk",
            "workspace_id": "workspace-one",
            "members": ["jira-alice"],
        }]
        with patch.object(sync, "SessionLocal", self.session_factory):
            result = sync._import_external_groups(
                _Adapter(),
                groups,
                [self.external_agent],
            )

        self.assertEqual(result["groups_created"], 1)
        self.assertEqual(result["memberships"], 1)
        with self.session_factory() as db:
            group = db.query(ExternalGroupRecord).one()
            membership = db.query(ExternalGroupMembershipRecord).one()
            self.assertEqual(group.name, "Service Desk")
            self.assertEqual(group.workspace_id, "workspace-one")
            self.assertEqual(membership.membership_kind, "member")

    def test_unchanged_group_sync_does_not_rewrite_memberships(self):
        self.external_agent["member_of"] = ["service-desk"]
        self._sync()
        groups = [{
            "id": "service-desk",
            "name": "Service Desk",
            "members": ["jira-alice"],
        }]
        with patch.object(sync, "SessionLocal", self.session_factory):
            sync._import_external_groups(_Adapter(), groups, [self.external_agent])

        membership_writes = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            normalized = " ".join(statement.lower().split())
            if (
                normalized.startswith(("insert", "update", "delete"))
                and "external_group_memberships" in normalized
            ):
                membership_writes.append(normalized)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(sync, "SessionLocal", self.session_factory):
                result = sync._import_external_groups(
                    _Adapter(), groups, [self.external_agent]
                )
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(result["memberships"], 1)
        self.assertEqual(membership_writes, [])
        with self.session_factory() as db:
            self.assertEqual(db.query(ExternalGroupMembershipRecord).count(), 1)

    def test_directory_import_uses_constant_identity_lookup_queries(self):
        agents = [
            {
                "accountId": f"jira-agent-{index}",
                "displayName": f"Provider Agent {index}",
                "emailAddress": f"agent-{index}@example.com",
                "active": True,
                "member_of": [f"service-desk-{index}"],
            }
            for index in range(40)
        ]
        groups = [
            {
                "id": f"service-desk-{index}",
                "name": f"Service Desk {index}",
                "members": [f"jira-agent-{index}"],
            }
            for index in range(40)
        ]
        identity_selects = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and (
                " from external_users " in normalized
                or " from external_groups " in normalized
            ):
                identity_selects.append(normalized)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(sync, "SessionLocal", self.session_factory):
                user_result = sync._import_external_users(_Adapter(), agents)
                group_result = sync._import_external_groups(_Adapter(), groups, agents)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(user_result["created"], 40)
        self.assertEqual(user_result["errors"], 0)
        self.assertEqual(group_result["groups_created"], 40)
        self.assertEqual(group_result["memberships"], 40)
        # One scoped user preload, one scoped group preload, and one membership
        # user lookup. Directory size must not add identity SELECTs.
        self.assertEqual(len(identity_selects), 3, identity_selects)

    def test_embedded_agent_identity_never_downgrades_to_shared_placeholder(self):
        with self.session_factory() as db:
            sync._upsert_embedded_external_user(
                db,
                binding_id="legacy",
                provider="freshservice",
                external_id="agent-1",
                user_type="agent",
                name="Kevin Rook",
                email="kevin@example.com",
            )
            db.flush()
            sync._upsert_embedded_external_user(
                db,
                binding_id="legacy",
                provider="freshservice",
                external_id="agent-1",
                user_type="agent",
                name="Freshservice agent",
                email="helpdesk@example.com",
            )
            agent = db.query(ExternalUserRecord).filter_by(
                external_id="agent-1", user_type="agent"
            ).one()
            self.assertEqual(agent.name, "Kevin Rook")
            self.assertEqual(agent.email, "kevin@example.com")

    def test_placeholder_agent_is_repaired_from_same_id_outgoing_evidence(self):
        with self.session_factory() as db:
            db.add(ExternalUserRecord(
                id="placeholder-agent",
                binding_id="legacy",
                provider="freshservice",
                external_id="agent-2",
                user_type="agent",
                name="Freshservice agent",
                email="helpdesk@example.com",
                active=True,
            ))
            db.add(TicketRecord(id="identity-ticket", subject="Identity evidence"))
            for index, name in enumerate([
                "Freshservice agent",
                "Freshservice agent",
                "Freshservice agent",
                "Chek Cheng",
                "Chek Cheng",
            ]):
                db.add(ExternalConversationRecord(
                    id=f"agent-conversation-{index}",
                    binding_id="legacy",
                    provider="freshservice",
                    ticket_id="identity-ticket",
                    provider_ticket_id="identity-ticket",
                    external_id=str(index),
                    body="Provider-authored evidence",
                    body_hash=str(index) * 64,
                    incoming=False,
                    is_private=False,
                    deleted=False,
                    public_tombstone=False,
                    revision_hash=f"{index + 1}" * 64,
                    author_external_id="agent-2",
                    author_name=name,
                    author_email="helpdesk@example.com",
                ))
            db.add(ExternalConversationRecord(
                id="incoming-requester-evidence",
                binding_id="legacy",
                provider="freshservice",
                ticket_id="identity-ticket",
                provider_ticket_id="identity-ticket",
                external_id="incoming",
                body="Requester evidence must not rename an agent",
                body_hash="a" * 64,
                incoming=True,
                is_private=False,
                deleted=False,
                public_tombstone=False,
                revision_hash="b" * 64,
                author_external_id="agent-2",
                author_name="Wrong Requester Name",
                author_email="wrong@example.com",
            ))
            db.commit()

            repaired = sync.reconcile_embedded_agent_identities(db)

            self.assertEqual(repaired, 1)
            agent = db.get(ExternalUserRecord, "placeholder-agent")
            self.assertEqual(agent.name, "Chek Cheng")
            self.assertEqual(agent.email, "helpdesk@example.com")


if __name__ == "__main__":
    unittest.main()
