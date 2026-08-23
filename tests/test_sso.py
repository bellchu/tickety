import asyncio
import json
import os
import time
import unittest
import urllib.parse
from unittest.mock import AsyncMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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

        os.environ["SSO_ENTRA_TENANT_ID"] = "contoso.onmicrosoft.com"
        with self.assertRaisesRegex(
            sso_service.SsoConfigurationError,
            "Directory .* GUID",
        ):
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
            self.assertEqual(
                sso_service.pkce_challenge(transaction.code_verifier),
                query["code_challenge"][0],
            )

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

    def test_auto_provisioned_identity_gets_only_agent_role(self):
        os.environ["SSO_AUTO_PROVISION"] = "true"
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="auto-subject",
            email="auto@example.com",
            name="Auto User",
        )

        with self.session_factory() as db:
            user, link = main._resolve_sso_user(db, identity, "entra")
            db.commit()
            self.assertEqual(user.role, "agent")
            self.assertTrue(user.is_active)
            self.assertEqual(link.user_id, user.id)

    def test_ambiguous_legacy_email_never_links_arbitrarily(self):
        identity = sso_service.OidcIdentity(
            issuer=str(self.metadata["issuer"]),
            subject="ambiguous-subject",
            email="duplicate@example.com",
            name="Duplicate User",
        )
        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id="u-duplicate-1",
                    email=identity.email,
                    name="First",
                    role="agent",
                    is_active=True,
                    password_hash="",
                ),
                UserRecord(
                    id="u-duplicate-2",
                    email=identity.email,
                    name="Second",
                    role="agent",
                    is_active=True,
                    password_hash="",
                ),
            ])
            db.commit()
            with self.assertRaisesRegex(PermissionError, "identity_conflict"):
                main._resolve_sso_user(db, identity, "entra")

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
