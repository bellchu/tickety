import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend import sso as sso_service
from app.backend.database import (
    Base,
    SessionRecord,
    SsoIdentityRecord,
    SsoTransactionRecord,
    UserRecord,
    get_db,
)


SSO_ENV_KEYS = (
    "APP_MODE",
    "COOKIE_SECURE",
    "FRONTEND_URL",
    "SSO_ALLOWED_DOMAINS",
    "SSO_ALLOWED_GROUP_IDS",
    "SSO_AUTO_PROVISION",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_ENABLED",
    "SSO_ENTRA_TENANT_ID",
    "SSO_OKTA_AUTH_SERVER_ID",
    "SSO_OKTA_DOMAIN",
    "SSO_PROVIDER",
    "SSO_REDIRECT_URI",
    "SSO_ACTIVE_TRANSACTION_LIMIT",
    "SSO_LOGIN_GLOBAL_PER_MINUTE",
    "SSO_LOGIN_SOURCE_PER_MINUTE",
)
TENANT_ID = "11111111-2222-4333-8444-555555555555"


class SsoConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.original = {key: os.environ.get(key) for key in SSO_ENV_KEYS}
        for key in SSO_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({
            "APP_MODE": "demo",
            "FRONTEND_URL": "http://testserver",
            "SSO_CLIENT_ID": "client-id",
            "SSO_CLIENT_SECRET": "client-secret",
            "SSO_ENABLED": "true",
        })

    def tearDown(self):
        for key in SSO_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({
            key: value for key, value in self.original.items() if value is not None
        })

    def test_entra_preset_derives_tenant_discovery_and_callback(self):
        os.environ.update({
            "SSO_PROVIDER": "entra",
            "SSO_ENTRA_TENANT_ID": TENANT_ID.upper(),
        })

        config = sso_service.resolve_sso_config()

        issuer = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
        self.assertEqual(config.provider_type, "entra")
        self.assertEqual(config.provider_name, "Microsoft Entra ID")
        self.assertEqual(config.expected_issuer, issuer)
        self.assertEqual(
            config.discovery_url,
            f"{issuer}/.well-known/openid-configuration",
        )
        self.assertEqual(
            config.redirect_uri,
            "http://testserver/api/auth/sso/callback",
        )

    def test_entra_requires_directory_tenant_guid(self):
        os.environ.update({
            "SSO_PROVIDER": "microsoft entra id",
            "SSO_ENTRA_TENANT_ID": "common",
        })

        with self.assertRaisesRegex(
            sso_service.SsoConfigurationError,
            "tenant-specific",
        ):
            sso_service.resolve_sso_config()

        os.environ["SSO_ENTRA_TENANT_ID"] = "example.onmicrosoft.com"
        with self.assertRaisesRegex(
            sso_service.SsoConfigurationError,
            "Directory .* GUID",
        ):
            sso_service.resolve_sso_config()

    def test_entra_group_allowlist_requires_and_normalizes_object_id_guids(self):
        os.environ.update({
            "SSO_PROVIDER": "entra",
            "SSO_ENTRA_TENANT_ID": TENANT_ID,
            "SSO_ALLOWED_GROUP_IDS": "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
        })

        self.assertEqual(
            sso_service.allowed_group_ids("entra"),
            {"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"},
        )
        sso_service.resolve_sso_config()
        os.environ["SSO_ALLOWED_GROUP_IDS"] = "IT agents"
        with self.assertRaisesRegex(sso_service.SsoConfigurationError, "object ID"):
            sso_service.resolve_sso_config()

    def test_okta_preset_defaults_to_org_and_supports_custom_issuer(self):
        os.environ.update({
            "SSO_PROVIDER": "okta",
            "SSO_OKTA_DOMAIN": "company.okta.com",
        })

        org_config = sso_service.resolve_sso_config()
        self.assertEqual(
            org_config.expected_issuer,
            "https://company.okta.com",
        )

        os.environ["SSO_OKTA_AUTH_SERVER_ID"] = "default"
        custom_config = sso_service.resolve_sso_config()
        self.assertEqual(
            custom_config.expected_issuer,
            "https://company.okta.com/oauth2/default",
        )

    def test_provider_aliases_keep_legacy_discovery_configuration_working(self):
        for provider in ("Azure AD", "Okta"):
            with self.subTest(provider=provider):
                os.environ["SSO_PROVIDER"] = provider
                os.environ["SSO_DISCOVERY_URL"] = (
                    "https://legacy.example.com/.well-known/openid-configuration"
                )
                config = sso_service.resolve_sso_config()
                self.assertEqual(
                    config.discovery_url,
                    "https://legacy.example.com/.well-known/openid-configuration",
                )
                self.assertIsNone(config.expected_issuer)

    def test_generic_oidc_keeps_legacy_discovery_override(self):
        os.environ.update({
            "SSO_PROVIDER": "Corporate Login",
            "SSO_DISCOVERY_URL": "https://id.example.com/.well-known/openid-configuration",
        })

        config = sso_service.resolve_sso_config()

        self.assertEqual(config.provider_type, "oidc")
        self.assertEqual(config.provider_name, "Corporate Login")
        self.assertIsNone(config.expected_issuer)

    def test_public_config_reports_enabled_but_not_ready_without_secret(self):
        os.environ.update({
            "SSO_PROVIDER": "entra",
            "SSO_ENTRA_TENANT_ID": TENANT_ID,
            "SSO_CLIENT_SECRET": "",
        })

        self.assertEqual(
            sso_service.public_sso_config(),
            {
                "enabled": True,
                "ready": False,
                "provider": "Microsoft Entra ID",
                "provider_type": "entra",
                "redirect_uri": "",
            },
        )

    def test_frontend_url_must_be_an_origin(self):
        os.environ.update({
            "SSO_PROVIDER": "entra",
            "SSO_ENTRA_TENANT_ID": TENANT_ID,
            "FRONTEND_URL": "http://testserver/tickety",
        })

        with self.assertRaisesRegex(sso_service.SsoConfigurationError, "origin"):
            sso_service.resolve_sso_config()

    def test_safe_next_path_blocks_external_and_auth_destinations(self):
        for unsafe in (
            "https://evil.example",
            "//evil.example/path",
            "/\\evil.example",
            "/login?next=/settings",
            "/api/auth/logout",
            "/ok\nLocation: https://evil.example",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(sso_service.safe_next_path(unsafe), "/")
        self.assertEqual(
            sso_service.safe_next_path("/settings?section=access#ignored"),
            "/settings?section=access",
        )


class SsoEndpointTests(unittest.TestCase):
    def setUp(self):
        self.original = {key: os.environ.get(key) for key in SSO_ENV_KEYS}
        for key in SSO_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({
            "APP_MODE": "demo",
            "FRONTEND_URL": "http://testserver",
            "SSO_CLIENT_ID": "client-id",
            "SSO_CLIENT_SECRET": "client-secret",
            "SSO_ENABLED": "true",
            "SSO_ENTRA_TENANT_ID": TENANT_ID,
            "SSO_PROVIDER": "entra",
        })
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(main.app)
        config = sso_service.resolve_sso_config()
        self.metadata = {
            "issuer": config.expected_issuer,
            "authorization_endpoint": "https://login.microsoftonline.com/authorize",
            "token_endpoint": "https://login.microsoftonline.com/token",
            "jwks_uri": "https://login.microsoftonline.com/keys",
        }

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        for key in SSO_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({
            key: value for key, value in self.original.items() if value is not None
        })

    def _begin_login(self, next_path="/"):
        with patch.object(
            sso_service,
            "fetch_oidc_metadata",
            new=AsyncMock(return_value=self.metadata),
        ):
            response = self.client.get(
                f"/auth/sso/login?{urllib.parse.urlencode({'next': next_path})}",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        location = urllib.parse.urlparse(response.headers["location"])
        query = urllib.parse.parse_qs(location.query)
        state = query["state"][0]
        return response, query, state

    def _callback_headers(self, state):
        return {"cookie": f"{main.SSO_STATE_COOKIE}={state}"}

    def _complete_callback(self, state, identity, *, code="callback-code"):
        with (
            patch.object(
                sso_service,
                "fetch_oidc_metadata",
                new=AsyncMock(return_value=self.metadata),
            ),
            patch.object(
                sso_service,
                "exchange_authorization_code",
                new=AsyncMock(return_value={"id_token": "signed-token"}),
            ),
            patch.object(
                sso_service,
                "resolve_oidc_identity",
                new=AsyncMock(return_value=identity),
            ),
        ):
            return self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'code': code, 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )

    def test_login_uses_pkce_nonce_single_use_state_and_preserves_destination(self):
        os.environ["COOKIE_SAMESITE"] = "strict"
        response, query, state = self._begin_login("/settings?section=access")

        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query["code_challenge"][0])
        self.assertTrue(query["nonce"][0])
        self.assertNotEqual(query["nonce"][0], state)
        self.assertIn("Path=/api/auth/sso", response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        with self.session_factory() as db:
            transaction = db.query(SsoTransactionRecord).one()
            self.assertNotEqual(transaction.state_hash, state)
            self.assertEqual(transaction.next_path, "/settings?section=access")
            self.assertEqual(transaction.nonce, query["nonce"][0])
            self.assertEqual(transaction.auth_epoch, 0)
            self.assertEqual(
                sso_service.pkce_challenge(transaction.code_verifier),
                query["code_challenge"][0],
            )

    def test_sso_login_rate_limit_runs_before_discovery_and_persists_no_extra_state(self):
        os.environ.update({
            "SSO_LOGIN_GLOBAL_PER_MINUTE": "5",
            "SSO_LOGIN_SOURCE_PER_MINUTE": "1",
        })
        discovery = AsyncMock(return_value=self.metadata)
        with patch.object(sso_service, "fetch_oidc_metadata", new=discovery):
            admitted = self.client.get("/auth/sso/login", follow_redirects=False)
            limited = self.client.get("/auth/sso/login", follow_redirects=False)

        self.assertEqual(admitted.status_code, 302)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "60")
        discovery.assert_awaited_once()
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 1)

    def test_source_limit_rolls_back_global_reservation_for_another_source(self):
        os.environ.update({
            "SSO_LOGIN_GLOBAL_PER_MINUTE": "2",
            "SSO_LOGIN_SOURCE_PER_MINUTE": "1",
        })
        source_a = SimpleNamespace(client=SimpleNamespace(host="198.51.100.10"))
        source_b = SimpleNamespace(client=SimpleNamespace(host="198.51.100.11"))
        now = datetime.utcnow().replace(second=0, microsecond=0)
        with self.session_factory() as db:
            main._reserve_sso_login_rate(db, source_a, now)
            db.commit()
            with self.assertRaises(HTTPException) as limited:
                main._reserve_sso_login_rate(db, source_a, now)
            self.assertEqual(limited.exception.status_code, 429)
            main._reserve_sso_login_rate(db, source_b, now)
            db.commit()
            global_bucket = db.query(main.AIRequestBucketRecord).filter_by(
                actor_id="sso-login-global",
                window_kind="sso_login_global",
                window_start=now,
            ).one()
            self.assertEqual(global_bucket.request_count, 2)
            self.assertEqual(
                db.query(main.AIRequestBucketRecord).filter_by(
                    actor_id=main._sso_login_source_id(source_a),
                    window_kind="sso_login_source",
                    window_start=now,
                ).one().request_count,
                1,
            )

    def test_sso_transaction_capacity_prunes_expired_state_before_readmitting(self):
        os.environ.update({
            "SSO_ACTIVE_TRANSACTION_LIMIT": "1",
            "SSO_CAPACITY_REJECT_GLOBAL_PER_MINUTE": "1",
            "SSO_LOGIN_GLOBAL_PER_MINUTE": "10",
            "SSO_LOGIN_SOURCE_PER_MINUTE": "10",
        })
        discovery = AsyncMock(return_value=self.metadata)
        with patch.object(sso_service, "fetch_oidc_metadata", new=discovery):
            admitted = self.client.get("/auth/sso/login", follow_redirects=False)
            full = self.client.get("/auth/sso/login", follow_redirects=False)
            self.assertEqual(admitted.status_code, 302)
            self.assertEqual(full.status_code, 429)
            with self.session_factory() as db:
                normal_buckets = {
                    row.window_kind: row.request_count
                    for row in db.query(main.AIRequestBucketRecord).filter(
                        main.AIRequestBucketRecord.window_kind.in_(
                            ("sso_login_global", "sso_login_source")
                        )
                    )
                }
                self.assertEqual(normal_buckets, {
                    "sso_login_global": 1,
                    "sso_login_source": 1,
                })
                self.assertEqual(
                    db.query(main.AIRequestBucketRecord).filter_by(
                        actor_id="sso-capacity-reject-global",
                        window_kind="sso_capacity_reject_global",
                    ).one().request_count,
                    1,
                )
            with patch.object(main, "_lock_auth_security_epoch", side_effect=AssertionError("breaker must precede epoch lock")):
                breaker_limited = self.client.get("/auth/sso/login", follow_redirects=False)
            self.assertEqual(breaker_limited.status_code, 429)
            self.assertEqual(discovery.await_count, 1)
            with self.session_factory() as db:
                db.query(SsoTransactionRecord).update(
                    {SsoTransactionRecord.expires_at: datetime.utcnow() - timedelta(seconds=1)},
                    synchronize_session=False,
                )
                db.commit()
                future = datetime.utcnow().replace(second=0, microsecond=0) + timedelta(minutes=1)
                main._reserve_sso_login_admission(
                    db,
                    SimpleNamespace(client=SimpleNamespace(host="198.51.100.20")),
                    state_hash="c" * 64,
                    nonce="recovered-nonce",
                    code_verifier="recovered-verifier",
                    next_path="/",
                    config=sso_service.resolve_sso_config(),
                    now=future,
                )

        # The next fixed window bypasses the breaker and performs the normal
        # capacity check again; the expired transaction was pruned in that
        # successful admission.
        self.assertEqual(discovery.await_count, 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 1)

    def test_sso_transaction_capacity_serializes_cross_session_admission(self):
        # A file-backed SQLite database gives each worker an independent
        # connection, approximating two API replicas while retaining a fast
        # portable regression test for the shared epoch serialization lock.
        descriptor, database_path = tempfile.mkstemp(prefix="tickety-sso-admission-", suffix=".sqlite")
        os.close(descriptor)
        engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        config = sso_service.resolve_sso_config()
        barrier = threading.Barrier(2)

        def reserve(suffix: str):
            db = sessions()
            try:
                barrier.wait(timeout=5)
                main._reserve_sso_login_admission(
                    db,
                    SimpleNamespace(client=SimpleNamespace(host=f"198.51.100.{suffix}")),
                    state_hash=(suffix * 64)[:64],
                    nonce=f"nonce-{suffix}",
                    code_verifier=f"verifier-{suffix}",
                    next_path="/",
                    config=config,
                    now=datetime.utcnow(),
                )
                return 302
            except HTTPException as exc:
                return exc.status_code
            finally:
                db.close()

        try:
            with patch.dict(os.environ, {"SSO_ACTIVE_TRANSACTION_LIMIT": "1"}, clear=False):
                with ThreadPoolExecutor(max_workers=2) as workers:
                    outcomes = list(workers.map(reserve, ("a", "b")))
            self.assertEqual(sorted(outcomes), [302, 429])
            with sessions() as db:
                self.assertEqual(db.query(SsoTransactionRecord).count(), 1)
        finally:
            engine.dispose()
            os.unlink(database_path)

    def test_callback_links_stable_subject_sets_session_and_cannot_replay(self):
        with self.session_factory() as db:
            db.add(UserRecord(
                id="u-existing",
                email="person@example.com",
                name="Existing User",
                role="admin",
                is_active=True,
                password_hash="",
            ))
            db.commit()
        _, _, state = self._begin_login("/settings?section=access")
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="stable-subject",
            email="person@example.com",
            name="Person Example",
        )
        exchange = AsyncMock(return_value={"id_token": "signed-token"})
        resolve = AsyncMock(return_value=identity)

        with (
            patch.object(
                sso_service,
                "fetch_oidc_metadata",
                new=AsyncMock(return_value=self.metadata),
            ),
            patch.object(sso_service, "exchange_authorization_code", new=exchange),
            patch.object(sso_service, "resolve_oidc_identity", new=resolve),
        ):
            response = self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'code': 'code-1', 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )
            replay = self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'code': 'code-1', 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "http://testserver/settings?section=access",
        )
        self.assertIn(f"{main.SESSION_COOKIE}=", response.headers["set-cookie"])
        self.assertIn("sso_error=expired_request", replay.headers["location"])
        exchange.assert_awaited_once()
        resolve.assert_awaited_once()
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 0)
            link = db.query(SsoIdentityRecord).one()
            self.assertEqual(link.user_id, "u-existing")
            self.assertEqual(link.subject, "stable-subject")
            self.assertEqual(db.query(SessionRecord).count(), 1)

            renamed_identity = sso_service.OidcIdentity(
                issuer=identity.issuer,
                subject=identity.subject,
                email="person.renamed@example.com",
                name="Renamed Person",
            )
            user, existing_link = main._resolve_sso_user(db, renamed_identity, "entra")
            self.assertEqual(user.id, "u-existing")
            self.assertEqual(existing_link.id, link.id)
            self.assertEqual(existing_link.email_at_link, "person.renamed@example.com")

    def test_callback_rejects_state_created_before_password_recovery(self):
        with self.session_factory() as db:
            db.add(UserRecord(
                id="u-recovery",
                email="recovery@example.com",
                name="Recovery User",
                role="agent",
                is_active=True,
                password_hash="old-password-hash",
            ))
            db.commit()
        _, _, state = self._begin_login("/settings?section=access")

        # This represents the same locked, atomic boundary used by a password
        # replacement: session revocation and the SSO lower bound commit
        # together after the authorization state already exists.
        with self.session_factory() as db:
            user = main._lock_user_record(db, "u-recovery")
            self.assertEqual(main._advance_user_auth_epoch(db, user), 1)
            db.query(SessionRecord).filter(SessionRecord.user_id == user.id).delete(
                synchronize_session=False
            )
            db.commit()

        response = self._complete_callback(
            state,
            sso_service.OidcIdentity(
                issuer=str(self.metadata["issuer"]),
                subject="recovery-subject",
                email="recovery@example.com",
                name="Recovery User",
            ),
            code="recovery-code",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("sso_error=account_recovery_required", response.headers["location"])
        self.assertNotIn(main.SESSION_COOKIE, response.headers.get("set-cookie", ""))
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 0)
            self.assertEqual(db.query(SessionRecord).count(), 0)
            self.assertEqual(db.get(UserRecord, "u-recovery").auth_not_before_epoch, 1)

    def test_callback_rejects_pre_deactivation_state_after_account_reactivation(self):
        with self.session_factory() as db:
            db.add(UserRecord(
                id="u-reactivated",
                email="reactivated@example.com",
                name="Reactivated User",
                role="agent",
                is_active=True,
                password_hash="",
            ))
            db.commit()
        _, _, state = self._begin_login("/tickets")

        with self.session_factory() as db:
            user = main._lock_user_record(db, "u-reactivated")
            user.is_active = False
            self.assertEqual(main._advance_user_auth_epoch(db, user), 1)
            db.query(SessionRecord).filter(SessionRecord.user_id == user.id).delete(
                synchronize_session=False
            )
            db.commit()
        # Re-enabling an account does not lower the recovery watermark.
        with self.session_factory() as db:
            user = main._lock_user_record(db, "u-reactivated")
            user.is_active = True
            db.commit()

        response = self._complete_callback(
            state,
            sso_service.OidcIdentity(
                issuer=str(self.metadata["issuer"]),
                subject="reactivated-subject",
                email="reactivated@example.com",
                name="Reactivated User",
            ),
            code="reactivated-code",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("sso_error=account_recovery_required", response.headers["location"])
        self.assertNotIn(main.SESSION_COOKIE, response.headers.get("set-cookie", ""))
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 0)
            self.assertEqual(db.query(SessionRecord).count(), 0)
            user = db.get(UserRecord, "u-reactivated")
            self.assertTrue(user.is_active)
            self.assertEqual(user.auth_not_before_epoch, 1)

    def test_unprovisioned_identity_returns_friendly_code(self):
        _, _, state = self._begin_login("/tickets")
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="new-subject",
            email="new@example.com",
            name="New User",
        )
        with (
            patch.object(
                sso_service,
                "fetch_oidc_metadata",
                new=AsyncMock(return_value=self.metadata),
            ),
            patch.object(
                sso_service,
                "exchange_authorization_code",
                new=AsyncMock(return_value={"id_token": "signed-token"}),
            ),
            patch.object(
                sso_service,
                "resolve_oidc_identity",
                new=AsyncMock(return_value=identity),
            ),
        ):
            response = self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'code': 'code-2', 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("sso_error=account_not_provisioned", response.headers["location"])
        self.assertIn("next=%2Ftickets", response.headers["location"])
        with self.session_factory() as db:
            self.assertEqual(db.query(SessionRecord).count(), 0)
            self.assertEqual(db.query(SsoIdentityRecord).count(), 0)

    def test_group_allowlist_is_fail_closed_before_account_linking(self):
        allowed_group = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        os.environ["SSO_ALLOWED_GROUP_IDS"] = allowed_group
        base = dict(
            issuer=str(self.metadata["issuer"]),
            subject="group-subject",
            email="group-user@example.com",
            name="Group User",
        )
        self.assertIsNone(main._sso_group_access(
            sso_service.OidcIdentity(**base, groups=frozenset({allowed_group})),
            "entra",
        ))
        self.assertEqual(main._sso_group_access(
            sso_service.OidcIdentity(**base, groups=frozenset()),
            "entra",
        ), "group_not_allowed")
        self.assertEqual(main._sso_group_access(
            sso_service.OidcIdentity(**base, groups_overage=True),
            "entra",
        ), "group_claim_overage")

    def test_callback_rejects_identity_outside_allowed_group(self):
        os.environ["SSO_ALLOWED_GROUP_IDS"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        os.environ["SSO_AUTO_PROVISION"] = "true"
        _, _, state = self._begin_login("/tickets")
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="wrong-group-subject",
            email="wrong-group@example.com",
            name="Wrong Group",
            groups=frozenset({"bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"}),
        )
        with (
            patch.object(
                sso_service,
                "fetch_oidc_metadata",
                new=AsyncMock(return_value=self.metadata),
            ),
            patch.object(
                sso_service,
                "exchange_authorization_code",
                new=AsyncMock(return_value={"id_token": "signed-token"}),
            ),
            patch.object(
                sso_service,
                "resolve_oidc_identity",
                new=AsyncMock(return_value=identity),
            ),
        ):
            response = self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'code': 'code-group', 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )

        self.assertIn("sso_error=group_not_allowed", response.headers["location"])
        self.assertIn("next=%2Ftickets", response.headers["location"])
        with self.session_factory() as db:
            self.assertEqual(db.query(SessionRecord).count(), 0)
            self.assertEqual(db.query(UserRecord).count(), 0)
            self.assertEqual(db.query(SsoIdentityRecord).count(), 0)

    def test_auto_provisioned_identity_gets_only_agent_role(self):
        os.environ["SSO_AUTO_PROVISION"] = "true"
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="auto-subject",
            email="auto@example.com",
            name="Auto User",
        )

        with self.session_factory() as db:
            epoch = main._lock_auth_security_epoch(db)
            epoch.epoch = 4
            user, link = main._resolve_sso_user(
                db,
                identity,
                "entra",
                authentication_epoch=4,
            )
            db.commit()
            self.assertEqual(user.role, "agent")
            self.assertTrue(user.is_active)
            self.assertEqual(link.user_id, user.id)
            self.assertEqual(user.auth_not_before_epoch, 4)

    def test_auto_provision_race_rechecks_the_winning_account_epoch(self):
        os.environ["SSO_AUTO_PROVISION"] = "true"
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="raced-auto-subject",
            email="raced-auto@example.com",
            name="Raced Auto User",
        )

        with self.session_factory() as db:
            epoch = main._lock_auth_security_epoch(db)
            epoch.epoch = 1
            db.commit()

            # Model the only path that reaches the unique-email retry: the
            # initial lookup saw no account, then an administrator created an
            # account with a newer authentication lower bound before flush.
            original_flush = db.flush

            def insert_racing_account(*_args, **_kwargs):
                # Session query autoflushes even when there are no pending
                # objects. Only replace the explicit auto-provision flush.
                if not db.new:
                    return original_flush(*_args, **_kwargs)
                db.rollback()
                db.expunge_all()
                with self.engine.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO users "
                        "(id, name, email, email_key, role, is_active, auth_not_before_epoch) "
                        "VALUES ('u-raced-auto', 'Raced Auto User', "
                        "'raced-auto@example.com', 'raced-auto@example.com', "
                        "'agent', 1, 1)"
                    ))
                raise IntegrityError("INSERT INTO users", {}, Exception("unique race"))

            with patch.object(db, "flush", side_effect=insert_racing_account):
                with self.assertRaisesRegex(PermissionError, "account_recovery_required"):
                    main._resolve_sso_user(
                        db,
                        identity,
                        "entra",
                        authentication_epoch=0,
                    )
            db.rollback()

    def test_recovery_refuses_to_overwrite_a_corrupt_user_epoch(self):
        with self.session_factory() as db:
            user = UserRecord(
                id="u-corrupt-epoch",
                email="corrupt-epoch@example.com",
                name="Corrupt Epoch",
                role="agent",
                is_active=True,
                auth_not_before_epoch=1,
            )
            db.add(user)
            db.commit()

            with self.assertRaisesRegex(RuntimeError, "user authentication security epoch"):
                main._advance_user_auth_epoch(db, user)
            db.rollback()

            persisted = db.get(UserRecord, user.id)
            self.assertEqual(persisted.auth_not_before_epoch, 1)

    def test_database_rejects_legacy_email_key_drift(self):
        with self.session_factory() as db:
            db.commit()
            with self.assertRaises(IntegrityError):
                db.execute(text(
                    "INSERT INTO users (id, name, email, role, is_active) VALUES "
                    "('u-legacy-drift', 'Legacy Drift', 'duplicate@example.com', "
                    "'agent', 1)"
                ))
                db.flush()
            db.rollback()

    def test_provider_denial_consumes_transaction_without_token_exchange(self):
        _, _, state = self._begin_login("/reports")
        exchange = AsyncMock()

        with patch.object(sso_service, "exchange_authorization_code", new=exchange):
            response = self.client.get(
                f"/auth/sso/callback?{urllib.parse.urlencode({'error': 'access_denied', 'state': state})}",
                headers=self._callback_headers(state),
                follow_redirects=False,
            )

        self.assertIn("sso_error=access_denied", response.headers["location"])
        self.assertIn("next=%2Freports", response.headers["location"])
        exchange.assert_not_awaited()
        with self.session_factory() as db:
            self.assertEqual(db.query(SsoTransactionRecord).count(), 0)


class OidcIdentityGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_entra_groups_are_normalized_from_verified_claims(self):
        config = sso_service.SsoRuntimeConfig(
            provider_type="entra",
            provider_name="Microsoft Entra ID",
            client_id="client-id",
            client_secret="client-secret",
            discovery_url="https://issuer.example.com/.well-known/openid-configuration",
            redirect_uri="http://testserver/api/auth/sso/callback",
            expected_issuer="https://issuer.example.com",
        )
        claims = {
            "iss": "https://issuer.example.com",
            "sub": "subject",
            "email": "agent@example.com",
            "email_verified": True,
            "name": "Agent",
            "groups": ["AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE", "not-a-guid"],
            "_claim_names": {"groups": "src1"},
        }
        with patch.object(
            sso_service,
            "validate_id_token",
            new=AsyncMock(return_value=claims),
        ):
            identity = await sso_service.resolve_oidc_identity(
                {"id_token": "verified-token"},
                {"issuer": claims["iss"]},
                config,
                nonce="nonce",
            )

        self.assertEqual(
            identity.groups,
            {"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"},
        )
        self.assertTrue(identity.groups_overage)

    async def test_identity_requires_explicit_boolean_verified_email(self):
        config = sso_service.SsoRuntimeConfig(
            provider_type="oidc",
            provider_name="Corporate Login",
            client_id="client-id",
            client_secret="client-secret",
            discovery_url="https://issuer.example.com/.well-known/openid-configuration",
            redirect_uri="http://testserver/api/auth/sso/callback",
            expected_issuer="https://issuer.example.com",
        )
        for value in (None, False, 1, "true"):
            with self.subTest(email_verified=value):
                claims = {
                    "iss": "https://issuer.example.com",
                    "sub": "subject",
                    "email": "agent@example.com",
                }
                if value is not None:
                    claims["email_verified"] = value
                with patch.object(
                    sso_service,
                    "validate_id_token",
                    new=AsyncMock(return_value=claims),
                ):
                    with self.assertRaisesRegex(
                        sso_service.SsoProtocolError,
                        "email is not verified",
                    ):
                        await sso_service.resolve_oidc_identity(
                            {"id_token": "verified-token"},
                            {"issuer": claims["iss"]},
                            config,
                            nonce="nonce",
                        )

    async def test_identity_never_uses_preferred_username_for_account_binding(self):
        config = sso_service.SsoRuntimeConfig(
            provider_type="oidc",
            provider_name="Corporate Login",
            client_id="client-id",
            client_secret="client-secret",
            discovery_url="https://issuer.example.com/.well-known/openid-configuration",
            redirect_uri="http://testserver/api/auth/sso/callback",
            expected_issuer="https://issuer.example.com",
        )
        claims = {
            "iss": "https://issuer.example.com",
            "sub": "subject",
            "preferred_username": "victim@example.com",
        }
        with patch.object(
            sso_service,
            "validate_id_token",
            new=AsyncMock(return_value=claims),
        ):
            with self.assertRaisesRegex(
                sso_service.SsoProtocolError,
                "verified addressable email",
            ):
                await sso_service.resolve_oidc_identity(
                    {"id_token": "verified-token"},
                    {"issuer": claims["iss"]},
                    config,
                    nonce="nonce",
                )


class IdTokenValidationTests(unittest.TestCase):
    def test_signature_audience_issuer_and_nonce_are_verified(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        public_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
        issuer = "https://issuer.example.com"
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": "client-id",
            "sub": "subject-1",
            "nonce": "nonce-1",
            "iat": now,
            "exp": now + 300,
            "email": "person@example.com",
        }
        token = jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"kid": "key-1"},
        )
        multi_audience_token = jwt.encode(
            {**claims, "aud": ["client-id", "another-client"]},
            private_key,
            algorithm="RS256",
            headers={"kid": "key-1"},
        )
        metadata = {
            "issuer": issuer,
            "jwks_uri": "https://issuer.example.com/keys",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        config = sso_service.SsoRuntimeConfig(
            provider_type="oidc",
            provider_name="OIDC",
            client_id="client-id",
            client_secret="secret",
            discovery_url=f"{issuer}/.well-known/openid-configuration",
            redirect_uri="https://tickety.example/api/auth/sso/callback",
            expected_issuer=None,
        )

        with patch.object(
            sso_service,
            "_fetch_jwks",
            new=AsyncMock(return_value={"keys": [public_jwk]}),
        ):
            verified = asyncio.run(
                sso_service.validate_id_token(token, metadata, config, nonce="nonce-1")
            )
            self.assertEqual(verified["sub"], "subject-1")
            with self.assertRaisesRegex(sso_service.SsoProtocolError, "nonce"):
                asyncio.run(
                    sso_service.validate_id_token(token, metadata, config, nonce="wrong")
                )
            with self.assertRaisesRegex(
                sso_service.SsoProtocolError,
                "authorized party",
            ):
                asyncio.run(
                    sso_service.validate_id_token(
                        multi_audience_token,
                        metadata,
                        config,
                        nonce="nonce-1",
                    )
                )


if __name__ == "__main__":
    unittest.main()
