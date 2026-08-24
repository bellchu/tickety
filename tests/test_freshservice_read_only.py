import ast
import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.backend import main
from app.backend.integrations import freshservice, registry
from app.backend.integrations.freshservice import FreshserviceAdapter


class FreshserviceReadOnlyContractTests(unittest.TestCase):
    def test_capabilities_permanently_reject_provider_mutations(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "readonly.freshservice.com",
            "FRESHSERVICE_API_KEY": "test-key",
            "FRESHSERVICE_OAUTH_SCOPES": (
                "freshservice.tickets.view freshservice.agents.manage "
                "freshservice.requesters.view"
            ),
        })
        manifest = adapter.capability_manifest()

        self.assertEqual(manifest["integration.mode"], {
            "status": "supported",
            "mode": "read_only",
        })
        self.assertEqual(manifest["requester.read"]["status"], "supported")
        self.assertEqual(manifest["conversation.read"]["status"], "supported")
        for capability in (
            "ticket.create",
            "ticket.update",
            "ticket.reply",
            "ticket.note",
            "ticket.attachment",
            "service_request.create",
        ):
            with self.subTest(capability=capability):
                self.assertEqual(manifest[capability]["status"], "unsupported")
                self.assertEqual(manifest[capability]["reason"], "read_only_sidecar")

    def test_data_adapter_contains_no_mutating_http_call(self):
        tree = ast.parse(inspect.getsource(freshservice))
        violations = []
        oauth_methods = {"oauth_exchange_code", "oauth_refresh"}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in oauth_methods:
                continue
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in {"post", "put", "patch", "delete"}
                ):
                    violations.append(f"{node.name}:{child.func.attr}")
        self.assertEqual(violations, [])
        self.assertFalse(hasattr(FreshserviceAdapter, "create_ticket"))
        self.assertFalse(hasattr(FreshserviceAdapter, "update_ticket_raw"))

    def test_oauth_scope_allowlist_rejects_ticket_write_access(self):
        self.assertEqual(
            FreshserviceAdapter._validate_oauth_scopes(
                "freshservice.tickets.view freshservice.agents.manage freshservice.requesters.view"
            ),
            "freshservice.tickets.view freshservice.agents.manage freshservice.requesters.view",
        )
        with self.assertRaisesRegex(ValueError, "read-only allowlist"):
            FreshserviceAdapter._validate_oauth_scopes(
                "freshservice.tickets.view freshservice.tickets.edit"
            )

    def test_external_directory_fetch_keeps_agents_and_requesters_typed(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "readonly.freshservice.com",
            "FRESHSERVICE_API_KEY": "test-key",
        })
        adapter.fetch_agents = AsyncMock(return_value=[{"id": 1, "name": "Agent"}])
        adapter.fetch_requesters = AsyncMock(return_value=[{"id": 2, "first_name": "Requester"}])

        users = asyncio.run(adapter.fetch_external_users())

        self.assertEqual(
            [(user["id"], user["user_type"]) for user in users],
            [(1, "agent"), (2, "requester")],
        )

    def test_conversation_parser_uses_plain_text_and_fails_without_stable_id(self):
        adapter = FreshserviceAdapter()
        parsed = adapter._parse_conversation({
            "id": 1001,
            "body": "<b>HTML</b>",
            "body_text": "Plain text",
            "private": False,
            "incoming": True,
            "user_id": 9,
            "created_at": "2026-08-24T01:00:00Z",
            "updated_at": "2026-08-24T01:01:00Z",
        })
        self.assertEqual(parsed.external_id, "1001")
        self.assertEqual(parsed.body, "Plain text")
        self.assertTrue(parsed.incoming)
        with self.assertRaisesRegex(ValueError, "stable ID"):
            adapter._parse_conversation({"body_text": "missing identity"})

    def test_ticket_inventory_enumerates_every_configured_workspace(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "readonly.freshservice.com",
            "FRESHSERVICE_API_KEY": "test-key",
            "FRESHSERVICE_WORKSPACE_IDS": "10,20",
        })
        responses = []
        for ticket_id, workspace_id in ((1, 10), (2, 20)):
            response = MagicMock(status_code=200, headers={})
            response.json.return_value = {
                "tickets": [{
                    "id": ticket_id,
                    "workspace_id": workspace_id,
                    "subject": f"Ticket {ticket_id}",
                    "description_text": "description",
                    "priority": 2,
                    "status": 2,
                }]
            }
            responses.append(response)
        adapter._rate_limited_get = AsyncMock(side_effect=responses)
        adapter.fetch_ticket_conversations = AsyncMock(return_value=[])
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=object())
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch.object(freshservice.httpx, "AsyncClient", return_value=client_context):
            tickets = asyncio.run(adapter.fetch_tickets_since(None))

        self.assertEqual([ticket.external_id for ticket in tickets], ["1", "2"])
        workspace_params = [
            call.args[2]["workspace_id"]
            for call in adapter._rate_limited_get.await_args_list
        ]
        self.assertEqual(workspace_params, ["10", "20"])

    def test_embedded_ticket_context_route_is_get_only(self):
        methods = set()
        for route in main.app.routes:
            if getattr(route, "path", None) == "/integrations/freshworks/tickets/{external_ticket_id}":
                methods.update(route.methods or set())
        self.assertEqual(methods, {"GET"})

    def test_production_ticket_lifecycle_is_disabled(self):
        with patch.object(main.settings_module, "is_production_mode", return_value=True):
            with self.assertRaises(HTTPException) as raised:
                main._require_demo_ticketing()
        self.assertEqual(raised.exception.status_code, 409)

    def test_default_provider_is_freshservice_in_production(self):
        with (
            patch.dict("os.environ", {"APP_MODE": "production"}, clear=True),
            patch.dict(registry._ADAPTERS, {}, clear=True),
        ):
            self.assertEqual(registry.configured_provider(), "freshservice")
            self.assertIsInstance(registry.get_adapter(), FreshserviceAdapter)

    def test_production_rejects_non_freshservice_provider(self):
        with (
            patch.dict(
                "os.environ",
                {"APP_MODE": "production", "ITSM_PROVIDER": "jira"},
                clear=True,
            ),
            patch.dict(registry._ADAPTERS, {}, clear=True),
        ):
            with self.assertRaisesRegex(ValueError, "read-only Freshservice sidecar"):
                registry.get_adapter()


if __name__ == "__main__":
    unittest.main()
