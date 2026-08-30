import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import directory_service
from app.backend.database import (
    AgentResolverTeamMappingRecord,
    Base,
    DirectoryPersonExternalIdentityRecord,
    DirectoryPersonLocalAccountRecord,
    DirectoryPersonRecord,
    DirectoryPersonResolverTeamMappingRecord,
    DirectorySyncRunRecord,
    ExternalUserRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
)


class DirectoryPeopleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        now = datetime.utcnow()
        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id="admin",
                    name="Admin",
                    email="admin@example.com",
                    role="admin",
                    is_active=True,
                ),
                UserRecord(
                    id="alice",
                    name="Alice Local",
                    email="alice@example.com",
                    role="agent",
                    is_active=True,
                ),
                UserRecord(
                    id="bob",
                    name="Bob Local",
                    email="bob@example.com",
                    role="supervisor",
                    is_active=True,
                ),
                ExternalUserRecord(
                    id="fs-agent-alice",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id="101",
                    user_type="agent",
                    name="Alice Agent",
                    email="alice@example.com",
                    active=True,
                    profile_json="{}",
                    fetched_at=now,
                ),
                ExternalUserRecord(
                    id="fs-requester-alice",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id="201",
                    user_type="requester",
                    name="Alice Requester",
                    email="alice@example.com",
                    active=True,
                    profile_json="{}",
                    fetched_at=now,
                ),
                ExternalUserRecord(
                    id="fs-requester-remote",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id="202",
                    user_type="requester",
                    name="Remote Requester",
                    email="remote@example.com",
                    active=True,
                    profile_json="{}",
                    fetched_at=now,
                ),
            ])
            db.commit()
            directory_service.ensure_directory_projection(db)
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_projection_keeps_requesters_remote_only_and_read_only(self):
        with self.session_factory() as db:
            directory_service.ensure_directory_projection(db)
            db.commit()
            remote_attachment = db.query(
                DirectoryPersonExternalIdentityRecord
            ).filter_by(external_user_id="fs-requester-remote").one()
            self.assertIsNone(db.query(DirectoryPersonLocalAccountRecord).filter_by(
                person_id=remote_attachment.person_id
            ).first())
            self.assertEqual(db.query(UserRecord).count(), 3)

            with self.assertRaises(directory_service.DirectoryIneligible):
                directory_service.replace_person_memberships(
                    db,
                    person_id=remote_attachment.person_id,
                    resolver_groups=["SERVICE_DESK"],
                    actor_id="admin",
                )

            with patch.dict(os.environ, {"REMOTE_REQUESTER_TEAM_ELIGIBLE": "true"}):
                person = directory_service.replace_person_memberships(
                    db,
                    person_id=remote_attachment.person_id,
                    resolver_groups=["SERVICE_DESK"],
                    actor_id="admin",
                )
            db.commit()
            self.assertEqual(person["role"], None)
            self.assertEqual(person["user_id"], None)
            self.assertEqual(person["resolver_groups"], ["SERVICE_DESK"])
            self.assertEqual(db.query(UserRecord).count(), 3)

    def test_exact_email_links_agent_and_requester_to_one_local_person(self):
        with self.session_factory() as db:
            preview = directory_service.preview_exact_email_links(db)
            alice_candidates = [
                row for row in preview["candidates"]
                if row["user_id"] == "alice"
            ]
            self.assertEqual(
                {row["user_type"] for row in alice_candidates},
                {"agent", "requester"},
            )

            result = directory_service.apply_exact_email_links(
                db, actor_id="admin"
            )
            db.commit()
            self.assertEqual(result["linked"], 2)
            person = directory_service.get_directory_person_for_user(db, "alice")
            self.assertTrue(person["linked"])
            self.assertEqual(
                set(person["source_types"]),
                {"local", "freshservice_agent", "freshservice_requester"},
            )
            self.assertEqual(len(person["identities"]), 2)
            self.assertEqual(
                db.query(UserExternalIdentityLinkRecord).filter_by(
                    user_id="alice"
                ).count(),
                1,
            )
            self.assertEqual(db.query(UserRecord).count(), 3)

    def test_exact_email_preview_uses_bounded_directory_queries(self):
        selects = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                selects.append(" ".join(statement.lower().split()))

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with self.session_factory() as db:
                preview = directory_service.preview_exact_email_links(db)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(preview["candidate_count"], 2)
        self.assertLessEqual(len(selects), 2, selects)

    def test_ambiguous_exact_email_is_reported_and_not_linked(self):
        with self.session_factory() as db:
            db.add(ExternalUserRecord(
                id="fs-requester-alice-duplicate",
                binding_id="binding-one",
                provider="freshservice",
                external_id="203",
                user_type="requester",
                name="Alice Duplicate",
                email="alice@example.com",
                active=True,
                profile_json="{}",
                fetched_at=datetime.utcnow(),
            ))
            db.flush()
            directory_service.ensure_directory_projection(db)
            preview = directory_service.preview_exact_email_links(db)
            self.assertEqual(preview["candidate_count"], 0)
            self.assertEqual(preview["conflict_count"], 1)
            self.assertEqual(
                preview["conflicts"][0]["reason"], "ambiguous_exact_email"
            )
            result = directory_service.apply_exact_email_links(
                db, actor_id="admin"
            )
            db.commit()
            self.assertEqual(result["linked"], 0)
            self.assertEqual(db.query(UserExternalIdentityLinkRecord).count(), 0)

    def test_identity_cannot_be_stolen_from_another_local_account(self):
        with self.session_factory() as db:
            directory_service.link_external_identity(
                db,
                user_id="alice",
                external_user_id="fs-agent-alice",
                actor_id="admin",
            )
            db.commit()
            with self.assertRaises(directory_service.DirectoryConflict):
                directory_service.link_external_identity(
                    db,
                    user_id="bob",
                    external_user_id="fs-agent-alice",
                    actor_id="admin",
                )
            db.rollback()
            alice = directory_service.get_directory_person_for_user(db, "alice")
            bob = directory_service.get_directory_person_for_user(db, "bob")
            self.assertEqual(
                {identity["external_user_id"] for identity in alice["identities"]},
                {"fs-agent-alice"},
            )
            self.assertEqual(bob["identities"], [])

    def test_exact_email_preview_refuses_an_identity_claimed_elsewhere(self):
        with self.session_factory() as db:
            directory_service.link_external_identity(
                db,
                user_id="bob",
                external_user_id="fs-requester-alice",
                actor_id="admin",
            )
            db.commit()
            preview = directory_service.preview_exact_email_links(db)
            self.assertEqual(preview["candidate_count"], 0)
            self.assertEqual(preview["conflict_count"], 1)

    def test_unlink_splits_identity_and_keeps_memberships_on_local_person(self):
        with self.session_factory() as db:
            linked = directory_service.link_external_identity(
                db,
                user_id="alice",
                external_user_id="fs-requester-remote",
                actor_id="admin",
            )
            linked = directory_service.replace_person_memberships(
                db,
                person_id=linked["id"],
                resolver_groups=["SOFTWARE_ENGINEERING"],
                actor_id="admin",
                expected_version=linked["version"],
            )
            attachment_id = linked["identities"][0]["attachment_id"]
            result = directory_service.unlink_external_identity(
                db,
                attachment_id=attachment_id,
                actor_id="admin",
                expected_person_version=linked["version"],
            )
            db.commit()
            self.assertEqual(
                result["source_person"]["resolver_groups"], ["SOFTWARE_ENGINEERING"]
            )
            self.assertEqual(result["detached_person"]["resolver_groups"], [])
            self.assertIsNone(result["detached_person"]["user_id"])
            self.assertEqual(
                db.query(DirectoryPersonResolverTeamMappingRecord).count(), 1
            )
            self.assertEqual(
                db.query(AgentResolverTeamMappingRecord).filter_by(
                    user_id="alice", resolver_group="SOFTWARE_ENGINEERING"
                ).count(),
                1,
            )
            merged = db.query(DirectoryPersonRecord).filter_by(state="merged").count()
            self.assertEqual(merged, 1)

    def test_link_unions_remote_membership_into_legacy_local_view(self):
        with self.session_factory() as db, patch.dict(
            os.environ, {"REMOTE_REQUESTER_TEAM_ELIGIBLE": "true"}
        ):
            attachment = db.query(
                DirectoryPersonExternalIdentityRecord
            ).filter_by(external_user_id="fs-requester-remote").one()
            directory_service.replace_person_memberships(
                db,
                person_id=attachment.person_id,
                resolver_groups=["SOFTWARE_ENGINEERING"],
                actor_id="admin",
            )
            linked = directory_service.link_external_identity(
                db,
                user_id="alice",
                external_user_id="fs-requester-remote",
                actor_id="admin",
            )
            db.commit()
            self.assertEqual(linked["resolver_groups"], ["SOFTWARE_ENGINEERING"])
            self.assertEqual(
                db.query(AgentResolverTeamMappingRecord).filter_by(
                    user_id="alice", resolver_group="SOFTWARE_ENGINEERING"
                ).count(),
                1,
            )
            self.assertEqual(
                db.query(UserExternalIdentityLinkRecord).filter_by(
                    user_id="alice"
                ).count(),
                0,
            )

    def test_directory_sync_lease_prevents_overlap(self):
        with patch.object(
            directory_service, "SessionLocal", self.session_factory
        ):
            run_id = directory_service._acquire_directory_sync_lease(
                binding_id="binding-one",
                provider="freshservice",
                lease_seconds=300,
            )
            self.assertIsNotNone(run_id)
            self.assertIsNone(directory_service._acquire_directory_sync_lease(
                binding_id="binding-one",
                provider="freshservice",
                lease_seconds=300,
            ))
            directory_service._finish_directory_sync(
                run_id=run_id,
                binding_id="binding-one",
                provider="freshservice",
                status="success",
                counts={"total": 3},
                error_kind=None,
            )
        with self.session_factory() as db:
            run = db.get(DirectorySyncRunRecord, run_id)
            self.assertEqual(run.status, "success")
            self.assertIsNotNone(run.finished_at)

    def test_partial_directory_sync_does_not_promote_projection(self):
        adapter = type("Adapter", (), {"provider_name": "freshservice"})()
        with (
            patch.object(directory_service, "SessionLocal", self.session_factory),
            patch.object(
                directory_service,
                "async_sync_external_users",
                new=AsyncMock(return_value={
                    "total": 3,
                    "created": 2,
                    "updated": 0,
                    "deactivated": 0,
                    "errors": 1,
                    "group_errors": 0,
                }),
            ),
            patch.object(
                directory_service, "ensure_directory_projection"
            ) as projection,
        ):
            result = asyncio.run(directory_service.run_directory_sync(
                adapter, binding_id="binding-one"
            ))
        self.assertEqual(result["status"], "partial")
        projection.assert_not_called()

    def test_directory_reads_do_not_promote_uncommitted_remote_rows(self):
        with self.session_factory() as db:
            attachment = db.query(
                DirectoryPersonExternalIdentityRecord
            ).filter_by(external_user_id="fs-requester-remote").one()
            person = db.get(DirectoryPersonRecord, attachment.person_id)
            db.delete(attachment)
            db.delete(person)
            db.commit()

            listed = directory_service.list_directory_people(
                db, source_type="requester", active=True
            )
            self.assertNotIn(
                "fs-requester-remote",
                {
                    identity["external_user_id"]
                    for row in listed["items"]
                    for identity in row["identities"]
                },
            )
            self.assertIsNone(db.query(
                DirectoryPersonExternalIdentityRecord
            ).filter_by(external_user_id="fs-requester-remote").first())


if __name__ == "__main__":
    unittest.main()
