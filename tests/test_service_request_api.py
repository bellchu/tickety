import asyncio
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    SessionRecord,
    ServiceItemRecord,
    ServiceRequestRecord,
    TicketRecord,
    TicketStatusConfigRecord,
    UserRecord,
    get_db,
)
from app.backend.schema import (
    ServiceRequestApprovalDecision,
    ServiceRequestCreate,
    ServiceRequestFulfillmentUpdate,
)


class ServiceRequestApiTests(unittest.TestCase):
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
                UserRecord(
                    id="auditor",
                    name="Auditor",
                    role="auditor",
                    is_active=True,
                ),
                SessionRecord(token="admin-session", user_id="admin"),
                SessionRecord(token="supervisor-session", user_id="supervisor"),
                SessionRecord(token="agent-session", user_id="agent"),
                SessionRecord(token="auditor-session", user_id="auditor"),
                TicketRecord(
                    id="ticket-1",
                    subject="Laptop request",
                    status="Open",
                    workflow_status="New",
                    ticket_type="incident",
                ),
                TicketRecord(
                    id="ticket-2",
                    subject="Access request",
                    status="Open",
                    workflow_status="New",
                    ticket_type="incident",
                ),
                TicketRecord(
                    id="ticket-3",
                    subject="New laptop request",
                    status="Open",
                    workflow_status="New",
                    ticket_type="incident",
                    created_at=datetime(2020, 1, 1, 0, 0),
                ),
                ServiceItemRecord(
                    id="service-1",
                    name="Managed laptop",
                    approval_required=True,
                ),
                ServiceItemRecord(id="service-2", name="Application access"),
                ServiceItemRecord(
                    id="service-3",
                    name="New employee laptop",
                    approval_required=True,
                    sla_hours=8,
                ),
                ServiceRequestRecord(
                    id="request-1",
                    ticket_id="ticket-1",
                    service_item_id="service-1",
                    approval_status="pending",
                    fulfillment_status="pending",
                    created_at=datetime(2026, 8, 26, 0, 0),
                ),
                ServiceRequestRecord(
                    id="request-2",
                    ticket_id="ticket-2",
                    service_item_id="service-2",
                    approval_status="approved",
                    fulfillment_status="pending",
                    created_at=datetime(2026, 8, 26, 0, 0),
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
        self.session_local_patch.start()
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.client = TestClient(main.app)
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        self.same_origin_headers = {"Sec-Fetch-Site": "same-origin"}

    def tearDown(self):
        self.auth_patch.stop()
        self.session_local_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    @staticmethod
    def _ticket_lifecycle(ticket):
        return {
            field: getattr(ticket, field)
            for field in (
                "ticket_type",
                "service_id",
                "workflow_status",
                "status",
                "resolution_due_at",
                "due_by",
                "resolved_at",
            )
        }

    def test_service_names_are_enriched_with_one_batched_query(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/service-requests")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200)
        by_id = {request["id"]: request for request in response.json()}
        self.assertEqual(by_id["request-1"]["service_name"], "Managed laptop")
        self.assertEqual(by_id["request-2"]["service_name"], "Application access")
        service_queries = [statement for statement in statements if "FROM service_items" in statement]
        self.assertEqual(len(service_queries), 1)

    def test_services_are_bounded_literal_and_publish_global_summary_headers(self):
        with self.session_factory() as db:
            db.add_all([
                ServiceItemRecord(
                    id="service-4",
                    name="Coverage 100% plan",
                    description="Percent-sign service",
                    category="Ops_%",
                ),
                ServiceItemRecord(
                    id="service-5",
                    name="Under_score plan",
                    category="OpsXA",
                ),
                ServiceItemRecord(
                    id="service-6",
                    name="Retired catalog item",
                    category="Retired",
                    is_active=False,
                ),
            ])
            db.commit()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            first = self.client.get("/services?limit=2")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(first.json()), 2)
        self.assertEqual(first.headers["x-page-limit"], "2")
        self.assertEqual(first.headers["x-page-offset"], "0")
        self.assertEqual(first.headers["x-has-more"], "true")
        self.assertEqual(first.headers["x-service-total"], "6")
        self.assertEqual(first.headers["x-service-active"], "5")
        self.assertEqual(first.headers["x-service-category-count"], "2")
        self.assertEqual(
            set(json.loads(first.headers["x-service-category-options"])),
            {"Ops_%", "OpsXA"},
        )
        self.assertEqual(
            first.headers["x-service-category-options-truncated"], "false"
        )
        service_selects = [
            statement for statement in statements if "FROM service_items" in statement
        ]
        self.assertEqual(len(service_selects), 3)

        repeated = self.client.get("/services?limit=2")
        second = self.client.get("/services?limit=2&offset=2")
        first_ids = [item["id"] for item in first.json()]
        self.assertEqual(
            [item["id"] for item in repeated.json()],
            first_ids,
        )
        self.assertTrue(set(first_ids).isdisjoint(
            {item["id"] for item in second.json()}
        ))

        literal_percent = self.client.get("/services", params={"search": "%"})
        literal_underscore = self.client.get("/services", params={"search": "_"})
        exact_category = self.client.get(
            "/services", params={"category": "Ops_%"}
        )
        inactive = self.client.get(
            "/services", params={"is_active": "false"}
        )
        self.assertEqual(
            {item["id"] for item in literal_percent.json()},
            {"service-4"},
        )
        self.assertEqual(
            {item["id"] for item in literal_underscore.json()},
            {"service-4", "service-5"},
        )
        self.assertEqual(
            {item["id"] for item in exact_category.json()},
            {"service-4"},
        )
        self.assertEqual(
            {item["id"] for item in inactive.json()},
            {"service-6"},
        )
        self.assertEqual(literal_percent.headers["x-service-total"], "6")

        for params in (
            {"search": "\x00"},
            {"category": "bad\x00category"},
            {"search": "x" * 201},
            {"category": "x" * 256},
            {"limit": "0"},
            {"limit": "201"},
            {"offset": "-1"},
            {"offset": "1000001"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get("/services", params=params).status_code,
                    422,
                )

    def test_service_requests_are_bounded_filtered_and_globally_summarized(self):
        with self.session_factory() as db:
            db.add_all([
                TicketRecord(id="ticket-4", subject="Fulfilled request"),
                TicketRecord(id="ticket-5", subject="Rejected request"),
                TicketRecord(id="ticket-6", subject="Literal wildcard request"),
                TicketRecord(id="ticket-7", subject="Legacy approval request"),
                ServiceRequestRecord(
                    id="request-3",
                    ticket_id="ticket-4",
                    service_item_id="service-1",
                    approval_status="not_required",
                    fulfillment_status="fulfilled",
                    created_at=datetime(2026, 8, 27, 0, 0),
                ),
                ServiceRequestRecord(
                    id="request-4",
                    ticket_id="ticket-5",
                    service_item_id="service-2",
                    approval_status="rejected",
                    fulfillment_status="cancelled",
                    created_at=datetime(2026, 8, 27, 0, 0),
                ),
                ServiceRequestRecord(
                    id="request-5",
                    ticket_id="ticket-6",
                    service_item_id="service-3",
                    justification="Need 100%_coverage",
                    approval_status="approved",
                    fulfillment_status="pending",
                    created_at=datetime(2026, 8, 28, 0, 0),
                ),
                ServiceRequestRecord(
                    id="request-6",
                    ticket_id="ticket-7",
                    service_item_id="service-2",
                    approval_status="legacy_unknown",
                    fulfillment_status="pending",
                    created_at=datetime(2026, 8, 25, 0, 0),
                ),
            ])
            db.commit()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            first = self.client.get("/service-requests?limit=2")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            [item["id"] for item in first.json()],
            ["request-5", "request-3"],
        )
        self.assertEqual(first.headers["x-has-more"], "true")
        self.assertEqual(first.headers["x-service-request-total"], "6")
        self.assertEqual(first.headers["x-service-request-open"], "4")
        self.assertEqual(first.headers["x-service-request-pending"], "4")
        self.assertEqual(first.headers["x-service-request-pending-approval"], "1")
        self.assertEqual(
            first.headers["x-service-request-awaiting-fulfillment"], "2"
        )
        list_selects = [
            statement
            for statement in statements
            if "FROM service_requests" in statement or "FROM service_items" in statement
        ]
        self.assertEqual(len(list_selects), 3)

        repeated = self.client.get("/service-requests?limit=2")
        second = self.client.get("/service-requests?limit=2&offset=2")
        self.assertEqual(repeated.json(), first.json())
        self.assertEqual(
            [item["id"] for item in second.json()],
            ["request-4", "request-1"],
        )

        for search in ("%", "_"):
            with self.subTest(search=search):
                response = self.client.get(
                    "/service-requests", params={"search": search}
                )
                self.assertEqual(
                    {item["id"] for item in response.json()},
                    {"request-5"},
                )
                self.assertEqual(response.headers["x-service-request-total"], "6")

        pending_approval = self.client.get(
            "/service-requests", params={"approval_status": "pending"}
        )
        fulfilled = self.client.get(
            "/service-requests", params={"fulfillment_status": "fulfilled"}
        )
        service_filter = self.client.get(
            "/service-requests", params={"service_item_id": "service-3"}
        )
        self.assertEqual(
            {item["id"] for item in pending_approval.json()},
            {"request-1"},
        )
        self.assertEqual(
            {item["id"] for item in fulfilled.json()},
            {"request-3"},
        )
        self.assertEqual(
            {item["id"] for item in service_filter.json()},
            {"request-5"},
        )

        for params in (
            {"search": "\x00"},
            {"service_item_id": "bad\x00id"},
            {"search": "x" * 201},
            {"service_item_id": "x" * 256},
            {"approval_status": "unknown"},
            {"fulfillment_status": "unknown"},
            {"limit": "0"},
            {"limit": "201"},
            {"offset": "-1"},
            {"offset": "1000001"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get("/service-requests", params=params).status_code,
                    422,
                )

    def test_operational_roles_can_read_service_lists_but_unknown_role_cannot(self):
        for role in ("admin", "supervisor", "agent"):
            with self.subTest(role=role):
                self.client.cookies.set(main.SESSION_COOKIE, f"{role}-session")
                self.assertEqual(self.client.get("/services").status_code, 200)
                self.assertEqual(
                    self.client.get("/service-requests").status_code,
                    200,
                )

        self.client.cookies.set(main.SESSION_COOKIE, "auditor-session")
        self.assertEqual(self.client.get("/services").status_code, 403)
        self.assertEqual(self.client.get("/service-requests").status_code, 403)

        self.client.cookies.delete(main.SESSION_COOKIE)
        with (
            patch.object(main.settings_module, "is_demo_mode", return_value=True),
            patch.object(main.settings_module, "get_bool", return_value=False),
        ):
            self.assertEqual(self.client.get("/services").status_code, 200)
            self.assertEqual(self.client.get("/service-requests").status_code, 200)
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

    def test_service_patch_is_partial_and_explicit_nulls_clear_safe_fields(self):
        first = self.client.patch(
            "/services/service-1",
            headers=self.same_origin_headers,
            json={"description": "Managed endpoint with standard support"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["approval_required"])
        self.assertEqual(first.json()["name"], "Managed laptop")

        populated = self.client.patch(
            "/services/service-1",
            headers=self.same_origin_headers,
            json={
                "category": "Hardware",
                "pricing": "$500",
                "sla_hours": 24,
                "approval_required": False,
            },
        )
        self.assertEqual(populated.status_code, 200, populated.text)
        self.assertFalse(populated.json()["approval_required"])

        cleared = self.client.patch(
            "/services/service-1",
            headers=self.same_origin_headers,
            json={
                "description": None,
                "category": None,
                "pricing": None,
                "sla_hours": None,
            },
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["description"], "")
        self.assertIsNone(cleared.json()["category"])
        self.assertIsNone(cleared.json()["pricing"])
        self.assertIsNone(cleared.json()["sla_hours"])
        self.assertFalse(cleared.json()["approval_required"])

        empty = self.client.patch(
            "/services/service-1",
            headers=self.same_origin_headers,
            json={},
        )
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json(), cleared.json())
        self.assertEqual(
            self.client.patch(
                "/services/service-1",
                headers=self.same_origin_headers,
                json={"name": None},
            ).status_code,
            422,
        )

    @patch.object(main.settings_module, "is_production_mode", return_value=False)
    def test_service_request_decisions_are_one_way_and_keep_ticket_consistent(
        self,
        _production_mode,
    ):
        approved = self.client.patch(
            "/service-requests/request-1/approval",
            headers=self.same_origin_headers,
            json={"decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        for decision in ("approved", "rejected"):
            with self.subTest(approval_retry=decision):
                self.assertEqual(
                    self.client.patch(
                        "/service-requests/request-1/approval",
                        headers=self.same_origin_headers,
                        json={"decision": decision},
                    ).status_code,
                    409,
                )

        fulfilled = self.client.patch(
            "/service-requests/request-2/fulfillment",
            headers=self.same_origin_headers,
            json={"status": "fulfilled"},
        )
        self.assertEqual(fulfilled.status_code, 200, fulfilled.text)
        for status in ("fulfilled", "cancelled"):
            with self.subTest(fulfillment_retry=status):
                self.assertEqual(
                    self.client.patch(
                        "/service-requests/request-2/fulfillment",
                        headers=self.same_origin_headers,
                        json={"status": status},
                    ).status_code,
                    409,
                )

        with self.session_factory() as db:
            db.add_all([
                TicketRecord(id="ticket-cancel", subject="Cancel this request"),
                TicketRecord(id="ticket-reject", subject="Reject this request"),
                ServiceRequestRecord(
                    id="request-cancel",
                    ticket_id="ticket-cancel",
                    service_item_id="service-2",
                    approval_status="approved",
                    fulfillment_status="pending",
                ),
                ServiceRequestRecord(
                    id="request-reject",
                    ticket_id="ticket-reject",
                    service_item_id="service-1",
                    approval_status="pending",
                    fulfillment_status="pending",
                ),
                TicketRecord(
                    id="ticket-inconsistent",
                    subject="Legacy inconsistent request",
                    status="Resolved",
                    workflow_status="Resolved",
                    resolved_at=datetime(2026, 8, 26, 12, 0),
                ),
                ServiceRequestRecord(
                    id="request-inconsistent",
                    ticket_id="ticket-inconsistent",
                    service_item_id="service-1",
                    approval_status="pending",
                    fulfillment_status="fulfilled",
                ),
            ])
            db.commit()

        cancelled = self.client.patch(
            "/service-requests/request-cancel/fulfillment",
            headers=self.same_origin_headers,
            json={"status": "cancelled"},
        )
        rejected = self.client.patch(
            "/service-requests/request-reject/approval",
            headers=self.same_origin_headers,
            json={"decision": "rejected"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(
            self.client.patch(
                "/service-requests/request-cancel/fulfillment",
                headers=self.same_origin_headers,
                json={"status": "fulfilled"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                "/service-requests/request-reject/approval",
                headers=self.same_origin_headers,
                json={"decision": "approved"},
            ).status_code,
            409,
        )
        for decision in ("approved", "rejected"):
            with self.subTest(inconsistent_approval=decision):
                self.assertEqual(
                    self.client.patch(
                        "/service-requests/request-inconsistent/approval",
                        headers=self.same_origin_headers,
                        json={"decision": decision},
                    ).status_code,
                    409,
                )

        with self.session_factory() as db:
            approved_ticket = db.get(TicketRecord, "ticket-1")
            fulfilled_ticket = db.get(TicketRecord, "ticket-2")
            cancelled_ticket = db.get(TicketRecord, "ticket-cancel")
            rejected_ticket = db.get(TicketRecord, "ticket-reject")
            inconsistent_request = db.get(
                ServiceRequestRecord,
                "request-inconsistent",
            )
            inconsistent_ticket = db.get(TicketRecord, "ticket-inconsistent")
            self.assertEqual(approved_ticket.status, "Pending Fulfillment")
            self.assertIsNone(approved_ticket.resolved_at)
            self.assertEqual(fulfilled_ticket.status, "Resolved")
            self.assertIsNotNone(fulfilled_ticket.resolved_at)
            self.assertEqual(cancelled_ticket.status, "Cancelled")
            self.assertEqual(cancelled_ticket.workflow_status, "Request Cancelled")
            self.assertIsNone(cancelled_ticket.resolved_at)
            self.assertEqual(rejected_ticket.status, "Cancelled")
            self.assertEqual(rejected_ticket.workflow_status, "Request Rejected")
            self.assertIsNone(rejected_ticket.resolved_at)
            self.assertEqual(inconsistent_request.approval_status, "pending")
            self.assertEqual(inconsistent_request.fulfillment_status, "fulfilled")
            self.assertEqual(inconsistent_ticket.status, "Resolved")
            self.assertIsNotNone(inconsistent_ticket.resolved_at)
            active_ticket_ids = {
                ticket_id
                for (ticket_id,) in db.query(TicketRecord.id).filter(
                    main.active_ticket_filter(db)
                ).all()
            }
            self.assertNotIn("ticket-cancel", active_ticket_ids)
            self.assertNotIn("ticket-reject", active_ticket_ids)

    @patch.object(main.settings_module, "is_production_mode", return_value=False)
    def test_terminal_tickets_cannot_be_converted_to_service_requests(
        self,
        _production_mode,
    ):
        resolved_at = datetime(2026, 8, 25, 12, 0)
        with self.session_factory() as db:
            db.add(TicketStatusConfigRecord(
                name="Done For Good",
                label="Done for good",
                is_open=False,
                is_terminal=True,
            ))
            db.add_all([
                TicketRecord(
                    id="terminal-default-ticket",
                    subject="Already resolved",
                    status="Resolved",
                    workflow_status="Resolved",
                    resolved_at=resolved_at,
                    points_awarded=75,
                    points_awarded_sent=True,
                ),
                TicketRecord(
                    id="terminal-custom-ticket",
                    subject="Custom terminal",
                    status="  dOnE fOr GoOd  ",
                    workflow_status="Done For Good",
                    resolved_at=resolved_at,
                    points_awarded=90,
                    points_awarded_sent=True,
                ),
            ])
            db.commit()

        for ticket_id in ("terminal-default-ticket", "terminal-custom-ticket"):
            with self.subTest(ticket_id=ticket_id):
                response = self.client.post(
                    "/service-requests",
                    headers=self.same_origin_headers,
                    json={
                        "ticket_id": ticket_id,
                        "service_item_id": "service-2",
                    },
                )
                self.assertEqual(response.status_code, 409, response.text)

        with self.session_factory() as db:
            self.assertEqual(
                db.query(ServiceRequestRecord).filter(
                    ServiceRequestRecord.ticket_id.in_((
                        "terminal-default-ticket",
                        "terminal-custom-ticket",
                    ))
                ).count(),
                0,
            )
            expected_points = {
                "terminal-default-ticket": 75,
                "terminal-custom-ticket": 90,
            }
            for ticket_id, points in expected_points.items():
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.resolved_at, resolved_at)
                self.assertEqual(ticket.points_awarded, points)
                self.assertTrue(ticket.points_awarded_sent)
                self.assertNotEqual(ticket.ticket_type, "request")

    def test_sqlite_concurrent_service_request_decisions_have_one_winner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(
                f"sqlite:///{temp_dir}/service-request-races.db",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            try:
                with session_factory() as db:
                    db.add(UserRecord(
                        id="race-admin",
                        name="Race Admin",
                        role="admin",
                        is_active=True,
                    ))
                    db.add(ServiceItemRecord(
                        id="race-service",
                        name="Race service",
                        is_active=True,
                    ))
                    for index in range(8):
                        db.add_all([
                            TicketRecord(
                                id=f"approval-ticket-{index}",
                                subject=f"Approval race {index}",
                            ),
                            ServiceRequestRecord(
                                id=f"approval-request-{index}",
                                ticket_id=f"approval-ticket-{index}",
                                approval_status="pending",
                                fulfillment_status="pending",
                            ),
                            TicketRecord(
                                id=f"fulfillment-ticket-{index}",
                                subject=f"Fulfillment race {index}",
                            ),
                            ServiceRequestRecord(
                                id=f"fulfillment-request-{index}",
                                ticket_id=f"fulfillment-ticket-{index}",
                                approval_status="approved",
                                fulfillment_status="pending",
                            ),
                            TicketRecord(
                                id=f"create-ticket-{index}",
                                subject=f"Create race {index}",
                            ),
                        ])
                    db.add_all([
                        TicketRecord(
                            id="stale-service-ticket",
                            subject="Stale service race",
                        ),
                        ServiceItemRecord(
                            id="stale-service",
                            name="Soon inactive service",
                            is_active=True,
                        ),
                    ])
                    db.commit()

                def race(handler, request_id, values):
                    barrier = threading.Barrier(2)

                    def invoke(value):
                        with session_factory() as db:
                            actor = db.get(UserRecord, "race-admin")
                            barrier.wait(timeout=10)
                            try:
                                asyncio.run(handler(request_id, value, db, actor))
                                return "ok"
                            except HTTPException as exc:
                                return exc.status_code

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        return [
                            future.result(timeout=30)
                            for future in (
                                executor.submit(invoke, values[0]),
                                executor.submit(invoke, values[1]),
                            )
                        ]

                def race_create(ticket_id):
                    barrier = threading.Barrier(2)
                    payload = ServiceRequestCreate(
                        ticket_id=ticket_id,
                        service_item_id="race-service",
                    )

                    def invoke():
                        with session_factory() as db:
                            barrier.wait(timeout=10)
                            try:
                                asyncio.run(main.create_service_request(payload, db))
                                return "ok"
                            except HTTPException as exc:
                                return exc.status_code

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        return [
                            future.result(timeout=30)
                            for future in (
                                executor.submit(invoke),
                                executor.submit(invoke),
                            )
                        ]

                with patch.object(
                    main.settings_module,
                    "is_production_mode",
                    return_value=False,
                ):
                    for index in range(8):
                        approval_results = race(
                            main.decide_service_request_approval,
                            f"approval-request-{index}",
                            (
                                ServiceRequestApprovalDecision(decision="approved"),
                                ServiceRequestApprovalDecision(decision="rejected"),
                            ),
                        )
                        fulfillment_results = race(
                            main.update_service_request_fulfillment,
                            f"fulfillment-request-{index}",
                            (
                                ServiceRequestFulfillmentUpdate(status="fulfilled"),
                                ServiceRequestFulfillmentUpdate(status="cancelled"),
                            ),
                        )
                        self.assertCountEqual(approval_results, ["ok", 409])
                        self.assertCountEqual(fulfillment_results, ["ok", 409])
                        self.assertCountEqual(
                            race_create(f"create-ticket-{index}"),
                            ["ok", 409],
                        )

                    deactivation_written = threading.Event()
                    creator_started = threading.Event()
                    allow_deactivation_commit = threading.Event()

                    def deactivate_service():
                        with session_factory() as db:
                            db.query(ServiceItemRecord).filter(
                                ServiceItemRecord.id == "stale-service"
                            ).update({ServiceItemRecord.is_active: False})
                            deactivation_written.set()
                            self.assertTrue(
                                allow_deactivation_commit.wait(timeout=10)
                            )
                            db.commit()

                    def create_from_stale_active_read():
                        self.assertTrue(deactivation_written.wait(timeout=10))
                        with session_factory() as db:
                            creator_started.set()
                            try:
                                asyncio.run(main.create_service_request(
                                    ServiceRequestCreate(
                                        ticket_id="stale-service-ticket",
                                        service_item_id="stale-service",
                                    ),
                                    db,
                                ))
                                return "ok"
                            except HTTPException as exc:
                                return exc.status_code

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        deactivator = executor.submit(deactivate_service)
                        creator = executor.submit(create_from_stale_active_read)
                        self.assertTrue(creator_started.wait(timeout=10))
                        allow_deactivation_commit.set()
                        deactivator.result(timeout=30)
                        self.assertEqual(creator.result(timeout=30), 404)

                with session_factory() as db:
                    for index in range(8):
                        approval = db.get(
                            ServiceRequestRecord,
                            f"approval-request-{index}",
                        )
                        approval_ticket = db.get(
                            TicketRecord,
                            f"approval-ticket-{index}",
                        )
                        if approval.approval_status == "approved":
                            self.assertEqual(
                                approval.fulfillment_status,
                                "pending",
                            )
                            self.assertEqual(
                                approval_ticket.status,
                                "Pending Fulfillment",
                            )
                        else:
                            self.assertEqual(approval.approval_status, "rejected")
                            self.assertEqual(
                                approval.fulfillment_status,
                                "cancelled",
                            )
                            self.assertEqual(
                                approval_ticket.status,
                                "Cancelled",
                            )
                            self.assertEqual(
                                approval_ticket.workflow_status,
                                "Request Rejected",
                            )
                        self.assertIsNone(approval_ticket.resolved_at)

                        fulfillment = db.get(
                            ServiceRequestRecord,
                            f"fulfillment-request-{index}",
                        )
                        fulfillment_ticket = db.get(
                            TicketRecord,
                            f"fulfillment-ticket-{index}",
                        )
                        if fulfillment.fulfillment_status == "fulfilled":
                            self.assertEqual(fulfillment_ticket.status, "Resolved")
                            self.assertIsNotNone(fulfillment_ticket.resolved_at)
                        else:
                            self.assertEqual(
                                fulfillment.fulfillment_status,
                                "cancelled",
                            )
                            self.assertEqual(
                                fulfillment_ticket.status,
                                "Cancelled",
                            )
                            self.assertEqual(
                                fulfillment_ticket.workflow_status,
                                "Request Cancelled",
                            )
                            self.assertIsNone(fulfillment_ticket.resolved_at)
                        self.assertEqual(
                            db.query(ServiceRequestRecord).filter(
                                ServiceRequestRecord.ticket_id
                                == f"create-ticket-{index}"
                            ).count(),
                            1,
                        )
                        create_ticket = db.get(
                            TicketRecord,
                            f"create-ticket-{index}",
                        )
                        self.assertEqual(create_ticket.ticket_type, "request")
                        self.assertEqual(create_ticket.service_id, "race-service")
                    self.assertFalse(
                        db.get(ServiceItemRecord, "stale-service").is_active
                    )
                    self.assertIsNone(
                        db.query(ServiceRequestRecord).filter(
                            ServiceRequestRecord.ticket_id
                            == "stale-service-ticket"
                        ).first()
                    )
            finally:
                engine.dispose()

    def test_production_service_request_writes_fail_before_changing_ticket_fields(self):
        with self.session_factory() as db:
            before = {
                ticket_id: self._ticket_lifecycle(db.get(TicketRecord, ticket_id))
                for ticket_id in ("ticket-1", "ticket-2", "ticket-3")
            }
            request_count = db.query(ServiceRequestRecord).count()

        with patch.object(main.settings_module, "is_production_mode", return_value=True):
            responses = (
                self.client.post(
                    "/service-requests",
                    headers=self.same_origin_headers,
                    json={"ticket_id": "ticket-3", "service_item_id": "service-3"},
                ),
                self.client.patch(
                    "/service-requests/request-1/approval",
                    headers=self.same_origin_headers,
                    json={"decision": "approved", "comment": "Approved"},
                ),
                self.client.patch(
                    "/service-requests/request-2/fulfillment",
                    headers=self.same_origin_headers,
                    json={"status": "fulfilled", "delivery_notes": "Delivered"},
                ),
            )

        for response in responses:
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("read-only", response.json()["detail"])
        with self.session_factory() as db:
            self.assertEqual(db.query(ServiceRequestRecord).count(), request_count)
            for ticket_id, lifecycle in before.items():
                self.assertEqual(
                    self._ticket_lifecycle(db.get(TicketRecord, ticket_id)),
                    lifecycle,
                )
            self.assertEqual(db.get(ServiceRequestRecord, "request-1").approval_status, "pending")
            self.assertEqual(db.get(ServiceRequestRecord, "request-2").fulfillment_status, "pending")

    def test_demo_service_request_can_be_created_approved_and_fulfilled(self):
        with patch.object(main.settings_module, "is_production_mode", return_value=False):
            created = self.client.post(
                "/service-requests",
                headers=self.same_origin_headers,
                json={
                    "ticket_id": "ticket-3",
                    "service_item_id": "service-3",
                    "justification": "New starter",
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            request_id = created.json()["id"]
            self.assertEqual(created.json()["approval_status"], "pending")

            approved = self.client.patch(
                f"/service-requests/{request_id}/approval",
                headers=self.same_origin_headers,
                json={"decision": "approved", "comment": "Manager approved"},
            )
            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertEqual(approved.json()["approval_status"], "approved")

            fulfilled = self.client.patch(
                f"/service-requests/{request_id}/fulfillment",
                headers=self.same_origin_headers,
                json={"status": "fulfilled", "delivery_notes": "Handed over"},
            )
            self.assertEqual(fulfilled.status_code, 200, fulfilled.text)
            self.assertEqual(fulfilled.json()["fulfillment_status"], "fulfilled")

        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-3")
            service_request = db.query(ServiceRequestRecord).filter(
                ServiceRequestRecord.ticket_id == "ticket-3"
            ).one()
            self.assertEqual(ticket.ticket_type, "request")
            self.assertEqual(ticket.service_id, "service-3")
            self.assertEqual(ticket.workflow_status, "Resolved")
            self.assertEqual(ticket.status, "Resolved")
            self.assertIsNotNone(ticket.resolution_due_at)
            self.assertIsNotNone(ticket.due_by)
            self.assertIsNotNone(ticket.resolved_at)
            self.assertEqual(
                (ticket.resolution_due_at - service_request.created_at).total_seconds(),
                8 * 60 * 60,
            )
            self.assertGreater(service_request.created_at, ticket.created_at)


if __name__ == "__main__":
    unittest.main()
