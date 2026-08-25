import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import email_service, main, settings
from app.backend.database import Base, ExternalUserRecord, UserRecord, get_db


class SendGridServiceTests(unittest.TestCase):
    def test_sendgrid_uses_private_personalizations_and_fixed_endpoint(self):
        response = MagicMock(status_code=202, headers={"x-message-id": "message-123"})
        client = AsyncMock()
        client.post.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {
                "SENDGRID_API_KEY": "SG.secret",
                "SENDGRID_FROM_EMAIL": "support@example.com",
                "SENDGRID_FROM_NAME": "Example Support",
                "SENDGRID_REPLY_TO_EMAIL": "help@example.com",
            }, clear=False),
            patch.object(email_service.httpx, "AsyncClient", return_value=context),
        ):
            message_id = asyncio.run(email_service.send_email([
                email_service.EmailAddress("One@Example.com", "One User"),
                email_service.EmailAddress("two@example.com", "Two User"),
            ], subject="Service update", body="Hello"))

        self.assertEqual(message_id, "message-123")
        request = client.post.call_args
        self.assertEqual(request.args[0], email_service.SENDGRID_MAIL_SEND_URL)
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer SG.secret")
        payload = request.kwargs["json"]
        self.assertEqual(len(payload["personalizations"]), 2)
        self.assertEqual(payload["personalizations"][0]["to"], [
            {"email": "one@example.com", "name": "One User"},
        ])
        self.assertEqual(payload["personalizations"][1]["to"], [
            {"email": "two@example.com", "name": "Two User"},
        ])
        self.assertNotIn("cc", payload)
        self.assertNotIn("bcc", payload)
        self.assertEqual(payload["reply_to"], {"email": "help@example.com"})

    def test_sendgrid_rejects_unconfigured_delivery_before_network_io(self):
        with (
            patch.dict(os.environ, {
                "SENDGRID_API_KEY": "",
                "SENDGRID_FROM_EMAIL": "",
            }, clear=False),
            patch.object(email_service.httpx, "AsyncClient") as async_client,
        ):
            with self.assertRaises(email_service.EmailConfigurationError):
                asyncio.run(email_service.send_email([
                    email_service.EmailAddress("agent@example.com", "Agent"),
                ], subject="Subject", body="Body"))
        async_client.assert_not_called()

    def test_sendgrid_provider_error_does_not_expose_response_body(self):
        response = MagicMock(status_code=401, headers={})
        client = AsyncMock()
        client.post.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.dict(os.environ, {
                "SENDGRID_API_KEY": "SG.secret",
                "SENDGRID_FROM_EMAIL": "support@example.com",
            }, clear=False),
            patch.object(email_service.httpx, "AsyncClient", return_value=context),
        ):
            with self.assertRaises(email_service.EmailDeliveryError) as raised:
                asyncio.run(email_service.send_email([
                    email_service.EmailAddress("agent@example.com", "Agent"),
                ], subject="Subject", body="Body"))
        self.assertEqual(raised.exception.provider_status, 401)
        self.assertNotIn("SG.secret", str(raised.exception))


class EmailSettingsTests(unittest.TestCase):
    def test_sendgrid_secret_is_masked_and_sender_fields_are_normalized(self):
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "SENDGRID_API_KEY": "old-secret",
                "SENDGRID_FROM_EMAIL": "old@example.com",
            }, clear=False),
            patch.object(settings, "_write_db_overrides") as write_overrides,
            patch.object(settings, "_reset_runtime"),
        ):
            result = settings.update_settings({
                "SENDGRID_API_KEY": "SG.new-secret",
                "SENDGRID_FROM_EMAIL": "Support@Example.com",
                "SENDGRID_FROM_NAME": "Example Support",
                "SENDGRID_REPLY_TO_EMAIL": "Replies@Example.com",
                "EMAIL_SENDS_PER_MINUTE": "7",
                "EMAIL_RECIPIENTS_PER_DAY": "800",
            }, actor_id="admin")

        self.assertEqual(result["SENDGRID_API_KEY"], "****")
        self.assertTrue(result["SENDGRID_API_KEY__set"])
        saved = write_overrides.call_args.args[0]
        self.assertEqual(saved["SENDGRID_FROM_EMAIL"], "support@example.com")
        self.assertEqual(saved["SENDGRID_REPLY_TO_EMAIL"], "replies@example.com")
        self.assertEqual(write_overrides.call_args.kwargs["approved_keys"], set(saved))

    def test_invalid_sendgrid_sender_and_limits_are_rejected(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "demo"}, clear=False),
            patch.object(settings, "_write_db_overrides") as write_overrides,
        ):
            with self.assertRaisesRegex(ValueError, "SENDGRID_FROM_EMAIL"):
                settings.update_settings({"SENDGRID_FROM_EMAIL": "Display <mail@example.com>"})
            with self.assertRaisesRegex(ValueError, "EMAIL_SENDS_PER_MINUTE"):
                settings.update_settings({"EMAIL_SENDS_PER_MINUTE": "0"})
        write_overrides.assert_not_called()


class EmailRouteTests(unittest.TestCase):
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
                UserRecord(
                    id="admin",
                    name="Admin Sender",
                    email="admin@example.com",
                    role="admin",
                    is_active=True,
                ),
                UserRecord(
                    id="agent",
                    name="Local Agent",
                    email="agent@example.com",
                    role="agent",
                    is_active=True,
                    title="Support Engineer",
                ),
                UserRecord(
                    id="inactive",
                    name="Inactive Agent",
                    email="inactive@example.com",
                    role="agent",
                    is_active=False,
                ),
                ExternalUserRecord(
                    id="external-agent-duplicate",
                    binding_id="binding",
                    provider="freshservice",
                    external_id="100",
                    user_type="agent",
                    name="Duplicate Provider Agent",
                    email="AGENT@example.com",
                    active=True,
                ),
                ExternalUserRecord(
                    id="external-agent",
                    binding_id="binding",
                    provider="freshservice",
                    external_id="101",
                    user_type="agent",
                    name="Provider Agent",
                    email="provider-agent@example.com",
                    active=True,
                ),
                ExternalUserRecord(
                    id="requester",
                    binding_id="binding",
                    provider="freshservice",
                    external_id="200",
                    user_type="requester",
                    name="Requesting User",
                    email="requester@example.com",
                    active=True,
                    title="Finance",
                ),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        def override_email_user():
            with self.session_factory() as db:
                return db.get(UserRecord, "admin")

        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_email_user] = override_email_user
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.roles_patch = patch.object(main, "_roles_required_for_request", return_value=None)
        self.auth_patch.start()
        self.roles_patch.start()
        self.environment = patch.dict(os.environ, {
            "APP_MODE": "production",
            "SENDGRID_API_KEY": "SG.route-secret",
            "SENDGRID_FROM_EMAIL": "support@example.com",
            "SENDGRID_FROM_NAME": "Tickety Support",
            "EMAIL_SENDS_PER_MINUTE": "5",
            "EMAIL_RECIPIENTS_PER_DAY": "500",
        }, clear=False)
        self.environment.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.environment.stop()
        self.roles_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_recipient_directories_are_separated_and_deduplicated(self):
        agents = self.client.get("/email/recipients?audience=agents")
        users = self.client.get("/email/recipients?audience=users")

        self.assertEqual(agents.status_code, 200)
        agent_payload = agents.json()
        self.assertEqual(
            {recipient["email"] for recipient in agent_payload["recipients"]},
            {"admin@example.com", "agent@example.com", "provider-agent@example.com"},
        )
        local_agent = next(
            recipient for recipient in agent_payload["recipients"]
            if recipient["email"] == "agent@example.com"
        )
        self.assertEqual(local_agent["id"], "local:agent")
        self.assertNotIn("inactive@example.com", {
            recipient["email"] for recipient in agent_payload["recipients"]
        })

        self.assertEqual(users.status_code, 200)
        self.assertEqual(users.json()["recipients"], [{
            "id": "external:requester",
            "name": "Requesting User",
            "email": "requester@example.com",
            "audience": "users",
            "source": "freshservice",
            "title": "Finance",
        }])

    def test_recipient_search_does_not_cross_audience_boundary(self):
        response = self.client.get(
            "/email/recipients?audience=users&search=finance"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        hidden = self.client.get(
            "/email/recipients?audience=users&search=provider-agent"
        )
        self.assertEqual(hidden.json()["recipients"], [])

    def test_send_resolves_directory_ids_and_adds_sender_identity(self):
        with patch.object(
            main,
            "send_sendgrid_email",
            new=AsyncMock(return_value="sendgrid-message"),
        ) as send:
            response = self.client.post("/email/send", json={
                "audience": "users",
                "recipient_ids": ["external:requester"],
                "subject": "Ticket update",
                "body": "Your request is ready.",
            })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {
            "status": "accepted",
            "recipient_count": 1,
            "message_id": "sendgrid-message",
        })
        recipients = send.call_args.args[0]
        self.assertEqual(recipients, [
            email_service.EmailAddress("requester@example.com", "Requesting User"),
        ])
        self.assertEqual(send.call_args.kwargs["subject"], "Ticket update")
        self.assertIn("Sent by Admin Sender via Tickety.", send.call_args.kwargs["body"])

    def test_arbitrary_or_cross_audience_recipient_ids_are_rejected(self):
        with patch.object(main, "send_sendgrid_email", new=AsyncMock()) as send:
            arbitrary = self.client.post("/email/send", json={
                "audience": "users",
                "recipient_ids": ["email:attacker@example.com"],
                "subject": "No relay",
                "body": "Body",
            })
            crossed = self.client.post("/email/send", json={
                "audience": "users",
                "recipient_ids": ["external:external-agent"],
                "subject": "No crossing",
                "body": "Body",
            })
        self.assertEqual(arbitrary.status_code, 422)
        self.assertEqual(crossed.status_code, 422)
        send.assert_not_awaited()

    def test_unconfigured_sendgrid_fails_before_resolving_or_sending(self):
        with (
            patch.dict(os.environ, {"SENDGRID_API_KEY": ""}, clear=False),
            patch.object(main, "send_sendgrid_email", new=AsyncMock()) as send,
        ):
            response = self.client.post("/email/send", json={
                "audience": "users",
                "recipient_ids": ["external:requester"],
                "subject": "Unavailable",
                "body": "Body",
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "SendGrid is not configured")
        send.assert_not_awaited()

    def test_email_sends_are_durably_rate_limited(self):
        with (
            patch.dict(os.environ, {"EMAIL_SENDS_PER_MINUTE": "1"}, clear=False),
            patch.object(
                main,
                "send_sendgrid_email",
                new=AsyncMock(return_value="accepted"),
            ) as send,
        ):
            payload = {
                "audience": "users",
                "recipient_ids": ["external:requester"],
                "subject": "Limited",
                "body": "Body",
            }
            first = self.client.post("/email/send", json=payload)
            second = self.client.post("/email/send", json=payload)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"], "email_rate_limit_exceeded")
        self.assertEqual(send.await_count, 1)


if __name__ == "__main__":
    unittest.main()
