import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import Base, TicketRecord
from app.backend.intelligence import (
    first_response_sla_status,
    resolution_sla_monitor_status,
    sla_status,
)
from app.backend.sla_policy import sla_eligible_filter, ticket_is_sla_exempt


class SlaPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.utcnow().replace(microsecond=0)

    def _ticket(self, ticket_id: str, **values) -> TicketRecord:
        defaults = {
            "subject": ticket_id,
            "status": "Open",
            "workflow_status": "Open",
            "priority": "P1",
            "external_source": "freshservice",
            "external_created_at": self.now - timedelta(hours=6),
            "external_updated_at": self.now - timedelta(minutes=5),
            "external_fr_due_by": self.now - timedelta(hours=4),
            "external_due_by": self.now - timedelta(hours=2),
            "external_conversations_synced_at": self.now,
        }
        defaults.update(values)
        return TicketRecord(id=ticket_id, **defaults)

    def test_closed_paused_and_on_hold_aliases_are_exempt_from_every_clock(self):
        statuses = (
            "Closed",
            "Resolved",
            "Paused",
            "Pending",
            "On Hold",
            "On-Hold",
            "On_Hold",
        )
        response = SimpleNamespace(
            incoming=False,
            provider_created_at=self.now - timedelta(hours=1),
            provider_updated_at=None,
            received_at=None,
        )

        for status in statuses:
            with self.subTest(status=status):
                ticket = self._ticket(f"ticket-{status}", status=status)
                point_in_time = sla_status(ticket, now=self.now)
                first_response = first_response_sla_status(
                    ticket, [response], now=self.now
                )
                resolution = resolution_sla_monitor_status(ticket, now=self.now)

                self.assertTrue(ticket_is_sla_exempt(ticket))
                self.assertNotIn(point_in_time["status"], {"breached", "at_risk"})
                self.assertEqual(point_in_time["overdue_hours"], 0.0)
                for clock in (first_response, resolution):
                    self.assertEqual(clock["status"], "unmeasured")
                    self.assertIsNone(clock["breach_state"])
                    self.assertEqual(clock["overdue_hours"], 0.0)

    def test_external_workflow_and_explicit_pause_fields_are_exempt(self):
        tickets = (
            self._ticket(
                "workflow-paused", status="Open", workflow_status="Paused"
            ),
            self._ticket(
                "external-on-hold", status="Open", external_status="On Hold"
            ),
            self._ticket(
                "explicit-pause", status="Open", sla_paused_at=self.now
            ),
        )

        for ticket in tickets:
            with self.subTest(ticket=ticket.id):
                self.assertTrue(ticket_is_sla_exempt(ticket))
                self.assertEqual(
                    resolution_sla_monitor_status(ticket, now=self.now)["status"],
                    "unmeasured",
                )

    def test_active_overdue_ticket_remains_breached(self):
        ticket = self._ticket("active-overdue")

        self.assertFalse(ticket_is_sla_exempt(ticket))
        self.assertEqual(sla_status(ticket, now=self.now)["status"], "breached")
        resolution = resolution_sla_monitor_status(ticket, now=self.now)
        self.assertEqual(resolution["status"], "breached")
        self.assertEqual(resolution["breach_state"], "active")

    def test_sql_filter_excludes_status_aliases_and_explicit_pauses(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        try:
            with session_factory() as db:
                db.add_all([
                    self._ticket("eligible"),
                    self._ticket("closed", status="Closed"),
                    self._ticket("paused", workflow_status="Paused"),
                    self._ticket("pending", external_status="Pending"),
                    self._ticket("on-hold", status="On-Hold"),
                    self._ticket("explicit-pause", sla_paused_at=self.now),
                    self._ticket("custom-terminal", status="Archived"),
                ])
                db.commit()

                ids = {
                    row.id
                    for row in db.query(TicketRecord).filter(
                        sla_eligible_filter({"Archived"})
                    ).all()
                }

            self.assertEqual(ids, {"eligible"})
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
