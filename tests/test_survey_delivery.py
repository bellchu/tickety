import hashlib
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    AIRequestBucketRecord,
    Base,
    SessionRecord,
    SurveyRecord,
    SurveyResponseRecord,
    SurveyTemplateRecord,
    TicketRecord,
    UserRecord,
    get_db,
)
from app.backend.email_service import EmailDeliveryError


PRODUCTION_ORIGIN = "https://tickety.nexora.com"
KNOWN_TOKEN = "A" * 43


class SurveyDeliveryTests(unittest.TestCase):
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
                    id="supervisor", name="Supervisor", role="supervisor", is_active=True
                ),
                UserRecord(id="agent", name="Agent", role="agent", is_active=True),
                SessionRecord(token="admin-session", user_id="admin"),
                SessionRecord(token="supervisor-session", user_id="supervisor"),
                SessionRecord(token="agent-session", user_id="agent"),
                SurveyTemplateRecord(
                    id=1,
                    name="Resolution CSAT",
                    question="How satisfied were you with the resolution?",
                    is_active=True,
                ),
                SurveyTemplateRecord(
                    id=2,
                    name="Inactive CSAT",
                    question="Old question",
                    is_active=False,
                ),
                TicketRecord(
                    id="closed-ticket",
                    subject="Resolved request",
                    status="Closed",
                    reporter="fallback@example.com",
                    external_requester_email="requester@example.com",
                    external_requester_name="Requesting User",
                ),
                TicketRecord(
                    id="open-ticket",
                    subject="Still open",
                    status="Open",
                    reporter="requester@example.com",
                ),
                TicketRecord(
                    id="invalid-email-ticket",
                    subject="Invalid requester",
                    status="Resolved",
                    reporter="not-an-email",
                ),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.session_local_patch = patch.object(main, "SessionLocal", self.session_factory)
        self.production_patch = patch.object(
            main.settings_module, "is_production_mode", return_value=True
        )
        self.demo_patch = patch.object(
            main.settings_module, "is_demo_mode", return_value=False
        )
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=True)
        self.environment = patch.dict(
            os.environ,
            {
                "APP_MODE": "production",
                "FRONTEND_URL": PRODUCTION_ORIGIN,
                "CORS_ALLOW_ORIGINS": PRODUCTION_ORIGIN,
                "SENDGRID_API_KEY": "SG.survey-test",
                "SENDGRID_FROM_EMAIL": "support@example.com",
                "SENDGRID_FROM_NAME": "Tickety OPS Tower Support",
                "EMAIL_SENDS_PER_MINUTE": "20",
                "EMAIL_RECIPIENTS_PER_DAY": "500",
                "SURVEY_LOOKUP_GLOBAL_PER_MINUTE": "600",
                "SURVEY_RESPOND_GLOBAL_PER_MINUTE": "100",
            },
            clear=False,
        )
        self.session_local_patch.start()
        self.production_patch.start()
        self.demo_patch.start()
        self.auth_patch.start()
        self.environment.start()
        self.client = TestClient(main.app)
        self.headers = {"Origin": PRODUCTION_ORIGIN}
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

    def tearDown(self):
        self.environment.stop()
        self.auth_patch.stop()
        self.demo_patch.stop()
        self.production_patch.stop()
        self.session_local_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _send(self, ticket_id="closed-ticket", template_id=1):
        return self.client.post(
            "/surveys/send",
            headers=self.headers,
            json={"ticket_id": ticket_id, "template_id": template_id},
        )

    def _add_public_survey(
        self,
        *,
        survey_id: str,
        token: str,
        status: str = "accepted",
        expires_at: datetime | None = None,
        responded_at: datetime | None = None,
    ):
        with self.session_factory() as db:
            db.add(SurveyRecord(
                id=survey_id,
                ticket_id="closed-ticket",
                template_id=1,
                response_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                response_expires_at=expires_at or datetime.utcnow() + timedelta(days=1),
                question_snapshot="How satisfied were you with the resolution?",
                recipient_email="requester@example.com",
                delivery_status=status,
                delivery_attempted_at=datetime.utcnow(),
                sent_at=datetime.utcnow() if status == "accepted" else None,
                responded_at=responded_at,
            ))
            db.commit()

    def test_send_stores_only_digest_and_reports_provider_acceptance(self):
        with (
            patch.object(main.secrets, "token_urlsafe", return_value=KNOWN_TOKEN),
            patch.object(
                main,
                "send_sendgrid_email",
                new=AsyncMock(return_value="sendgrid-message-id"),
            ) as send,
        ):
            response = self._send()

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["delivery_status"], "accepted")
        self.assertEqual(payload["delivery_message_id"], "sendgrid-message-id")
        self.assertIsNotNone(payload["sent_at"])
        self.assertNotIn(KNOWN_TOKEN, response.text)

        recipients = send.call_args.args[0]
        self.assertEqual(recipients[0].email, "requester@example.com")
        body = send.call_args.kwargs["body"]
        self.assertIn(
            f"{PRODUCTION_ORIGIN}/portal/survey#token={KNOWN_TOKEN}",
            body,
        )
        self.assertNotIn("?token=", body)
        with self.session_factory() as db:
            survey = db.query(SurveyRecord).one()
            self.assertEqual(
                survey.response_token_hash,
                hashlib.sha256(KNOWN_TOKEN.encode()).hexdigest(),
            )
            self.assertNotIn(KNOWN_TOKEN, " ".join(
                str(value) for value in survey.__dict__.values()
            ))
            self.assertEqual(survey.recipient_email, "requester@example.com")
            self.assertEqual(survey.sent_by, "admin")

        stats = self.client.get("/surveys/stats")
        self.assertEqual(stats.json()["total_sent"], 1)

    def test_agent_cannot_send_survey(self):
        self.client.cookies.set(main.SESSION_COOKIE, "agent-session")
        with patch.object(main, "send_sendgrid_email", new=AsyncMock()) as send:
            response = self._send()

        self.assertEqual(response.status_code, 403, response.text)
        send.assert_not_awaited()
        with self.session_factory() as db:
            self.assertEqual(db.query(SurveyRecord).count(), 0)

    def test_send_validates_provider_template_ticket_state_and_email(self):
        with patch.object(main, "send_sendgrid_email", new=AsyncMock()) as send:
            inactive = self._send(template_id=2)
            missing_template = self._send(template_id=999)
            open_ticket = self._send(ticket_id="open-ticket")
            invalid_email = self._send(ticket_id="invalid-email-ticket")
            with patch.dict(os.environ, {"SENDGRID_API_KEY": ""}, clear=False):
                unconfigured = self._send()

        self.assertEqual(inactive.status_code, 422)
        self.assertEqual(missing_template.status_code, 422)
        self.assertEqual(open_ticket.status_code, 409)
        self.assertEqual(invalid_email.status_code, 422)
        self.assertEqual(unconfigured.status_code, 503)
        send.assert_not_awaited()
        with self.session_factory() as db:
            self.assertEqual(db.query(SurveyRecord).count(), 0)

    def test_send_rejects_nul_and_normalizes_ticket_id(self):
        with patch.object(
            main,
            "send_sendgrid_email",
            new=AsyncMock(return_value="normalized-message"),
        ) as send:
            invalid = self._send(ticket_id="bad\x00ticket")
            normalized = self._send(ticket_id="  closed-ticket  ")

        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(normalized.status_code, 202, normalized.text)
        send.assert_awaited_once()

    def test_eligible_ticket_search_is_terminal_server_side_and_paginated(self):
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="historic-resolution",
                subject="Historic resolved VPN request",
                status="Resolved",
                reporter="historic@example.com",
                updated_at=datetime.utcnow() - timedelta(days=365),
            ))
            db.add_all([
                TicketRecord(
                    id=f"recent-open-{index:03d}",
                    subject=f"Recent open ticket {index:03d}",
                    status="Open",
                    reporter="requester@example.com",
                    updated_at=datetime.utcnow(),
                )
                for index in range(205)
            ])
            db.commit()

        found = self.client.get(
            "/surveys/eligible-tickets",
            params={"search": "Historic resolved VPN", "limit": 10},
        )
        first_page = self.client.get(
            "/surveys/eligible-tickets",
            params={"limit": 1, "offset": 0},
        )

        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual([ticket["id"] for ticket in found.json()], ["historic-resolution"])
        self.assertEqual(found.headers["x-has-more"], "false")
        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(len(first_page.json()), 1)
        self.assertEqual(first_page.headers["x-page-limit"], "1")
        self.assertEqual(first_page.headers["x-page-offset"], "0")
        self.assertEqual(first_page.headers["x-has-more"], "true")
        self.assertNotEqual(first_page.json()[0]["status"], "Open")

    def test_production_link_origin_is_fixed_and_fail_closed(self):
        with (
            patch.dict(os.environ, {"FRONTEND_URL": "https://alternate.example"}),
            patch.object(main, "send_sendgrid_email", new=AsyncMock()) as send,
        ):
            response = self._send()

        self.assertEqual(response.status_code, 503, response.text)
        send.assert_not_awaited()
        with self.session_factory() as db:
            self.assertEqual(db.query(SurveyRecord).count(), 0)

    def test_provider_failure_is_audited_but_not_counted_as_sent_and_can_retry(self):
        delivery = AsyncMock(side_effect=[EmailDeliveryError(500), "retry-message"])
        with patch.object(main, "send_sendgrid_email", new=delivery):
            failed = self._send()
            retried = self._send()

        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertEqual(retried.status_code, 202, retried.text)
        with self.session_factory() as db:
            rows = db.query(SurveyRecord).order_by(SurveyRecord.created_at).all()
            self.assertEqual([row.delivery_status for row in rows], ["failed", "accepted"])
            self.assertIsNone(rows[0].sent_at)
            self.assertEqual(rows[0].delivery_error, "provider_500")
            self.assertIsNone(rows[0].delivery_message_id)
        stats = self.client.get("/surveys/stats").json()
        self.assertEqual(stats["total_sent"], 1)
        self.assertEqual(stats["responded"], 0)

    def test_ambiguous_provider_failure_keeps_capability_usable_and_blocks_resend(self):
        with (
            patch.object(main.secrets, "token_urlsafe", return_value=KNOWN_TOKEN),
            patch.object(
                main,
                "send_sendgrid_email",
                new=AsyncMock(side_effect=EmailDeliveryError()),
            ) as send,
        ):
            uncertain = self._send()
            duplicate = self._send()

        self.assertEqual(uncertain.status_code, 502, uncertain.text)
        self.assertIn("outcome is unknown", uncertain.json()["detail"])
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        send.assert_awaited_once()
        with self.session_factory() as db:
            survey = db.query(SurveyRecord).one()
            self.assertEqual(survey.delivery_status, "uncertain")
            self.assertEqual(survey.delivery_error, "delivery_outcome_unknown")
            self.assertIsNotNone(survey.active_delivery_key)

        self.client.cookies.clear()
        lookup = self.client.post(
            "/portal/survey/lookup",
            headers=self.headers,
            json={"token": KNOWN_TOKEN},
        )
        self.assertEqual(lookup.status_code, 200, lookup.text)
        submitted = self.client.post(
            "/portal/survey/respond",
            headers=self.headers,
            json={"token": KNOWN_TOKEN, "rating": 5, "comment": "Delivered"},
        )
        self.assertEqual(submitted.status_code, 201, submitted.text)
        with self.session_factory() as db:
            reconciled = db.query(SurveyRecord).one()
            self.assertEqual(reconciled.delivery_status, "accepted")
            self.assertIsNotNone(reconciled.sent_at)
            self.assertIsNone(reconciled.delivery_error)
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        stats = self.client.get("/surveys/stats").json()
        self.assertEqual(stats["total_sent"], 1)
        self.assertEqual(stats["responded"], 1)
        self.assertEqual(stats["avg_rating"], 5.0)
        report = self.client.get("/reports/summary")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["csat_proxy"], 100.0)

    def test_public_lookup_and_one_time_response_use_post_body_capability(self):
        self._add_public_survey(survey_id="public-survey", token=KNOWN_TOKEN)
        self.client.cookies.clear()

        lookup = self.client.post(
            "/portal/survey/lookup",
            headers=self.headers,
            json={"token": KNOWN_TOKEN},
        )
        submitted = self.client.post(
            "/portal/survey/respond",
            headers=self.headers,
            json={"token": KNOWN_TOKEN, "rating": 5, "comment": "Excellent"},
        )
        replay = self.client.post(
            "/portal/survey/respond",
            headers=self.headers,
            json={"token": KNOWN_TOKEN, "rating": 1, "comment": "Replay"},
        )

        self.assertEqual(lookup.status_code, 200, lookup.text)
        self.assertEqual(set(lookup.json()), {"question", "expires_at"})
        self.assertNotIn("ticket", lookup.text.lower())
        self.assertNotIn("recipient", lookup.text.lower())
        self.assertEqual(lookup.headers["cache-control"], "no-store")
        self.assertEqual(submitted.status_code, 201, submitted.text)
        self.assertEqual(submitted.json(), {"status": "submitted"})
        self.assertEqual(replay.status_code, 409, replay.text)
        with self.session_factory() as db:
            self.assertEqual(db.query(SurveyResponseRecord).count(), 1)
            response = db.query(SurveyResponseRecord).one()
            self.assertEqual(response.rating, 5)
            self.assertEqual(response.comment, "Excellent")
            actor_ids = [
                row.actor_id for row in db.query(AIRequestBucketRecord).filter(
                    AIRequestBucketRecord.window_kind.like("survey_%")
                ).all()
            ]
        self.assertTrue(actor_ids)
        self.assertTrue(all(KNOWN_TOKEN not in actor_id for actor_id in actor_ids))

    def test_invalid_expired_and_unaccepted_tokens_share_public_error(self):
        expired_token = "B" * 43
        failed_token = "C" * 43
        self._add_public_survey(
            survey_id="expired-survey",
            token=expired_token,
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        self._add_public_survey(
            survey_id="failed-survey",
            token=failed_token,
            status="failed",
        )
        self.client.cookies.clear()

        responses = [
            self.client.post(
                "/portal/survey/lookup", headers=self.headers, json={"token": token}
            )
            for token in ("malformed", "D" * 43, expired_token, failed_token)
        ]

        self.assertEqual([response.status_code for response in responses], [404] * 4)
        self.assertEqual(
            {response.json()["detail"] for response in responses},
            {"Survey link is invalid or expired"},
        )
        with self.session_factory() as db:
            capability_buckets = db.query(AIRequestBucketRecord).filter(
                AIRequestBucketRecord.window_kind == "survey_lookup_minute"
            ).count()
            global_actors = {
                row.actor_id
                for row in db.query(AIRequestBucketRecord).filter(
                    AIRequestBucketRecord.window_kind.like("survey_lookup_global_%")
                )
            }
        self.assertEqual(capability_buckets, 0)
        self.assertEqual(global_actors, {"survey-lookup-global"})

    def test_public_endpoints_require_exact_explicit_production_origin(self):
        self._add_public_survey(survey_id="origin-survey", token=KNOWN_TOKEN)
        self.client.cookies.clear()

        cross_origin = self.client.post(
            "/portal/survey/lookup",
            headers={"Origin": "https://attacker.example"},
            json={"token": KNOWN_TOKEN},
        )
        no_origin = self.client.post(
            "/portal/survey/lookup",
            json={"token": KNOWN_TOKEN},
        )

        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(no_origin.status_code, 403)

    def test_replayed_public_responses_are_durably_rate_limited(self):
        self._add_public_survey(
            survey_id="limited-survey",
            token=KNOWN_TOKEN,
            responded_at=datetime.utcnow(),
        )
        self.client.cookies.clear()

        statuses = [
            self.client.post(
                "/portal/survey/respond",
                headers=self.headers,
                json={"token": KNOWN_TOKEN, "rating": 5, "comment": "Replay"},
            ).status_code
            for _ in range(6)
        ]

        self.assertEqual(statuses, [409, 409, 409, 409, 409, 429])
        with self.session_factory() as db:
            actors = {
                row.actor_id for row in db.query(AIRequestBucketRecord).filter(
                    AIRequestBucketRecord.window_kind == "survey_respond_minute"
                )
            }
        self.assertEqual(len(actors), 1)
        self.assertNotIn(KNOWN_TOKEN, next(iter(actors)))

    def test_database_unique_constraint_rejects_concurrent_duplicate_response(self):
        self._add_public_survey(survey_id="unique-survey", token=KNOWN_TOKEN)
        with self.session_factory() as first:
            first.add(SurveyResponseRecord(survey_id="unique-survey", rating=5))
            first.commit()
        with self.session_factory() as second:
            second.add(SurveyResponseRecord(survey_id="unique-survey", rating=1))
            with self.assertRaises(IntegrityError):
                second.commit()
            second.rollback()

    def test_database_unique_constraint_reserves_one_active_delivery(self):
        delivery_key = main._survey_delivery_key(
            "closed-ticket",
            1,
            "requester@example.com",
        )
        with self.session_factory() as first:
            first.add(SurveyRecord(
                id="active-delivery-one",
                ticket_id="closed-ticket",
                template_id=1,
                active_delivery_key=delivery_key,
                delivery_status="pending",
            ))
            first.commit()
        with self.session_factory() as second:
            second.add(SurveyRecord(
                id="active-delivery-two",
                ticket_id="closed-ticket",
                template_id=1,
                active_delivery_key=delivery_key,
                delivery_status="pending",
            ))
            with self.assertRaises(IntegrityError):
                second.commit()
            second.rollback()


if __name__ == "__main__":
    unittest.main()
