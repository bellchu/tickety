import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import intelligence, main, sync_worker
from app.backend.ai_eligibility import terminal_status_names
from app.backend.database import (
    Base,
    ExternalGroupRecord,
    TicketRecord,
    TicketStatusConfigRecord,
)


class IntelligenceTerminalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(microsecond=0)

    def tearDown(self):
        self.engine.dispose()

    def _ticket(self, ticket_id: str, status: str, **values) -> TicketRecord:
        defaults = {
            "subject": ticket_id,
            "reporter": "dynamic-policy@example.com",
            "status": status,
            "workflow_status": "Open",
            "external_status": "Open",
            "priority": "P1",
            "complexity": 1,
            "external_source": "freshservice",
            "external_created_at": self.now - timedelta(hours=10),
            "external_updated_at": self.now - timedelta(hours=1),
            "external_due_by": self.now - timedelta(hours=2),
            "external_conversations_synced_at": self.now,
        }
        defaults.update(values)
        return TicketRecord(id=ticket_id, **defaults)

    def test_dynamic_terminal_policy_matches_sql_and_python_intelligence(self):
        with self.session_factory() as db:
            db.add_all([
                TicketStatusConfigRecord(
                    name="K",
                    name_key="k",
                    label="Terminal K",
                    is_open=False,
                    is_terminal=True,
                ),
                TicketStatusConfigRecord(
                    name="Done",
                    name_key="done",
                    label="Done",
                    is_open=False,
                    is_terminal=True,
                ),
                self._ticket("ascii-terminal", "K"),
                self._ticket("unicode-lookalike", "K"),
                self._ticket("custom-terminal", "Done"),
                self._ticket("ordinary-open", "Open"),
            ])
            db.commit()

            terminals = terminal_status_names(db)
            tickets = {
                ticket.id: ticket
                for ticket in db.query(TicketRecord).order_by(TicketRecord.id).all()
            }
            python_open = {
                ticket_id
                for ticket_id, ticket in tickets.items()
                if intelligence._open(ticket, terminals)
            }
            sql_open = {
                ticket.id for ticket in main._open_ticket_query(db).all()
            }
            health = intelligence.account_health(
                db, "dynamic-policy@example.com"
            )
            alerts = intelligence.proactive_alerts(db, now=self.now)

            self.assertEqual(python_open, {"ordinary-open", "unicode-lookalike"})
            self.assertEqual(sql_open, python_open)
            self.assertFalse(
                intelligence._open(self._ticket("builtin", "Closed"), {"Done"})
            )
            self.assertEqual(health["open"], 2)
            self.assertEqual(health["total"], 4)
            self.assertEqual(alerts["total_open_tickets"], 2)
            self.assertEqual(alerts["analyzed_tickets"], 2)

            done = tickets["custom-terminal"]
            kelvin = tickets["unicode-lookalike"]
            done_sla = intelligence.sla_status(done, self.now, terminals)
            kelvin_sla = intelligence.sla_status(kelvin, self.now, terminals)
            done_first_response = intelligence.first_response_sla_status(
                done, [], now=self.now, terminal_statuses=terminals
            )
            kelvin_first_response = intelligence.first_response_sla_status(
                kelvin, [], now=self.now, terminal_statuses=terminals
            )
            done_resolution = intelligence.resolution_sla_monitor_status(
                done, now=self.now, terminal_statuses=terminals
            )
            kelvin_resolution = intelligence.resolution_sla_monitor_status(
                kelvin, now=self.now, terminal_statuses=terminals
            )
            done_friction = intelligence.customer_friction_signal(
                done, [], now=self.now, terminal_statuses=terminals
            )
            kelvin_friction = intelligence.customer_friction_signal(
                kelvin, [], now=self.now, terminal_statuses=terminals
            )
            done_routing = intelligence.team_routing_decision(
                None,
                None,
                ticket_status=done.status,
                terminal_statuses=terminals,
            )
            kelvin_routing = intelligence.team_routing_decision(
                None,
                None,
                ticket_status=kelvin.status,
                terminal_statuses=terminals,
            )

            self.assertFalse(done_sla["is_open"])
            self.assertEqual(done_sla["status"], "on_track")
            self.assertEqual(done_sla["overdue_hours"], 0.0)
            self.assertTrue(kelvin_sla["is_open"])
            self.assertEqual(kelvin_sla["status"], "breached")
            self.assertEqual(done_first_response["status"], "unmeasured")
            self.assertEqual(done_resolution["status"], "unmeasured")
            self.assertFalse(done_first_response["is_open"])
            self.assertFalse(done_resolution["is_open"])
            self.assertEqual(kelvin_first_response["breach_state"], "active")
            self.assertEqual(kelvin_resolution["breach_state"], "active")
            self.assertFalse(done_friction["flagged"])
            self.assertTrue(kelvin_friction["flagged"])
            self.assertEqual(done_routing.status, "not_applicable")
            self.assertEqual(kelvin_routing.status, "unrouted_review")
            self.assertLess(
                intelligence.escalation_risk(done, self.now, terminals),
                intelligence.escalation_risk(kelvin, self.now, terminals),
            )

    def test_historical_profiles_and_level_zero_remain_closed_resolved_only(self):
        with self.session_factory() as db:
            db.add(TicketStatusConfigRecord(
                name="Done",
                name_key="done",
                label="Done",
                is_open=False,
                is_terminal=True,
            ))
            db.add(ExternalGroupRecord(
                id="group-row",
                binding_id="legacy",
                provider="freshservice",
                external_id="group-1",
                name="Service Desk",
            ))
            common = {
                "reporter": "history@example.com",
                "priority": "P3",
                "complexity": 1,
                "external_source": "freshservice",
                "external_group_id": "group-1",
                "external_category": "Password Reset",
                "ai_suggested_team": "SERVICE_DESK",
                "ai_status": "completed",
                "external_created_at": self.now - timedelta(days=3),
                "external_updated_at": self.now - timedelta(days=2),
                "summary": "Password reset completed. Please sign in again.",
            }
            db.add_all([
                self._ticket(
                    "closed-history",
                    " CLOSED ",
                    subject="Password reset needed",
                    **common,
                ),
                self._ticket(
                    "custom-terminal-history",
                    "Done",
                    subject="Password reset needed",
                    **common,
                ),
                self._ticket(
                    "cancelled-history",
                    "Cancelled",
                    subject="Password reset needed",
                    **common,
                ),
            ])
            db.commit()

            profiles, profiles_truncated = intelligence.build_group_profiles(
                db,
                since=self.now - timedelta(days=30),
                group_keys={("legacy", "freshservice", "group-1")},
                trusted_route_ticket_ids={"closed-history"},
            )
            study = intelligence.run_level_zero_study(
                db, months=6, now=self.now
            )

            profile = profiles[("legacy", "freshservice", "group-1")]
            self.assertEqual(profile["level_samples"], 1)
            self.assertEqual(profile["functional_samples"], 1)
            self.assertFalse(profiles_truncated)
            self.assertEqual(study["analyzed_tickets"], 1)
            self.assertEqual(
                {item["ticket_id"] for item in study["items"]},
                {"closed-history"},
            )

    def test_group_profiles_are_scoped_and_signal_bounded_aggregate_truncation(self):
        legacy_scope = str(
            intelligence._binding_key_scope(
                TicketRecord.binding_id,
                "legacy",
            ).compile(
                dialect=self.engine.dialect,
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        self.assertIn("tickets.binding_id is null", legacy_scope)
        self.assertIn("tickets.binding_id = 'legacy'", legacy_scope)

        with self.session_factory() as db:
            db.add_all([
                ExternalGroupRecord(
                    id="profile-group-relevant",
                    binding_id="legacy",
                    provider="freshservice",
                    external_id="relevant-group",
                    name="Relevant Group",
                ),
                ExternalGroupRecord(
                    id="profile-group-unrelated",
                    binding_id="legacy",
                    provider="freshservice",
                    external_id="unrelated-group",
                    name="Unrelated Group",
                ),
                self._ticket(
                    "profile-relevant-one",
                    "Closed",
                    external_group_id="relevant-group",
                    external_category="Email",
                ),
                self._ticket(
                    "profile-relevant-two",
                    "Resolved",
                    external_group_id="relevant-group",
                    external_category="Network",
                ),
                self._ticket(
                    "profile-unrelated",
                    "Closed",
                    external_group_id="unrelated-group",
                    external_category="Hardware",
                ),
            ])
            db.commit()

            with patch.object(intelligence, "GROUP_PROFILE_AGGREGATE_LIMIT", 1):
                profiles, truncated = intelligence.build_group_profiles(
                    db,
                    since=self.now - timedelta(days=30),
                    group_keys={("legacy", "freshservice", "relevant-group")},
                )

            self.assertTrue(truncated)
            self.assertEqual(
                set(profiles),
                {("legacy", "freshservice", "relevant-group")},
            )
            self.assertEqual(
                profiles[("legacy", "freshservice", "relevant-group")]["group_name"],
                "Relevant Group",
            )

    def test_group_profiles_keep_same_provider_ids_in_distinct_scopes(self):
        with self.session_factory() as db:
            db.add_all([
                ExternalGroupRecord(
                    id="freshservice-shared-group",
                    binding_id="shared-binding",
                    provider="freshservice",
                    external_id="shared-group",
                    name="Freshservice Network Operations",
                ),
                ExternalGroupRecord(
                    id="jira-shared-group",
                    binding_id="shared-binding",
                    provider="jira",
                    external_id="shared-group",
                    name="Jira Applications",
                ),
                self._ticket(
                    "freshservice-shared-history",
                    "Resolved",
                    binding_id="shared-binding",
                    external_source="freshservice",
                    external_group_id="shared-group",
                    external_category="Network",
                    complexity=5,
                ),
                self._ticket(
                    "jira-shared-history",
                    "Resolved",
                    binding_id="shared-binding",
                    external_source="jira",
                    external_group_id="shared-group",
                    external_category="Application",
                    priority="P3",
                    complexity=1,
                ),
            ])
            db.commit()

            profiles, truncated = intelligence.build_group_profiles(
                db,
                since=self.now - timedelta(days=30),
                group_keys={
                    ("shared-binding", "freshservice", "shared-group"),
                    ("shared-binding", "jira", "shared-group"),
                },
            )

        self.assertFalse(truncated)
        self.assertEqual(
            profiles[("shared-binding", "freshservice", "shared-group")]["group_name"],
            "Freshservice Network Operations",
        )
        self.assertEqual(
            profiles[("shared-binding", "jira", "shared-group")]["group_name"],
            "Jira Applications",
        )
        self.assertNotEqual(
            profiles[("shared-binding", "freshservice", "shared-group")]["inferred_level"],
            profiles[("shared-binding", "jira", "shared-group")]["inferred_level"],
        )

    def test_worker_risk_backfill_passes_the_dynamic_terminal_policy(self):
        with self.session_factory() as db:
            db.add(TicketStatusConfigRecord(
                name="Done",
                name_key="done",
                label="Done",
                is_open=False,
                is_terminal=True,
            ))
            db.add(self._ticket(
                "risk-backfill",
                "Open",
                ai_reasoning="Current triage result",
                ai_status="completed",
                escalation_risk=0,
                summary="Summary already available",
                recommended_solution="Resolution already available",
            ))
            db.commit()
            db.query(TicketRecord).filter(
                TicketRecord.id == "risk-backfill"
            ).update(
                {TicketRecord.escalation_risk_backfilled_at: None},
                synchronize_session=False,
            )
            db.commit()

        with (
            patch.object(sync_worker, "SessionLocal", self.session_factory),
            patch.object(
                intelligence,
                "escalation_risk",
                return_value=37,
            ) as risk,
        ):
            sync_worker._risk_backfill_job()

        risk.assert_called_once()
        self.assertIn("done", risk.call_args.kwargs["terminal_statuses"])
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "risk-backfill")
            self.assertEqual(ticket.escalation_risk, 37)
            self.assertIsNotNone(ticket.escalation_risk_backfilled_at)

    def test_worker_risk_backfill_is_bounded_and_zero_is_not_reprocessed(self):
        with self.session_factory() as db:
            db.add_all([
                self._ticket(
                    f"risk-page-{index:02d}",
                    "Open",
                    ai_reasoning="Current triage result",
                    ai_status="completed",
                    escalation_risk=0,
                    summary="Summary already available",
                    recommended_solution="Resolution already available",
                    updated_at=self.now + timedelta(seconds=index),
                )
                for index in range(18)
            ])
            db.commit()
            db.query(TicketRecord).filter(
                TicketRecord.id.like("risk-page-%")
            ).update(
                {TicketRecord.escalation_risk_backfilled_at: None},
                synchronize_session=False,
            )
            db.commit()

        processed = []

        def zero_risk(ticket, **_kwargs):
            processed.append(ticket.id)
            return 0

        with (
            patch.dict(
                os.environ,
                {"AI_RISK_BACKFILL_PER_SWEEP": "7"},
                clear=False,
            ),
            patch.object(sync_worker, "SessionLocal", self.session_factory),
            patch.object(intelligence, "escalation_risk", side_effect=zero_risk),
        ):
            sync_worker._risk_backfill_job()
            first_page = list(processed)
            sync_worker._risk_backfill_job()

        self.assertEqual(len(first_page), 7)
        self.assertEqual(len(processed), 14)
        self.assertEqual(len(set(processed)), 14)
        self.assertEqual(
            first_page,
            [f"risk-page-{index:02d}" for index in range(7)],
        )
        with self.session_factory() as db:
            completed = db.query(TicketRecord).filter(
                TicketRecord.id.in_(processed),
                TicketRecord.escalation_risk == 0,
                TicketRecord.escalation_risk_backfilled_at.isnot(None),
            ).count()
            remaining = db.query(TicketRecord).filter(
                TicketRecord.id.like("risk-page-%"),
                TicketRecord.escalation_risk_backfilled_at.is_(None),
            ).count()
        self.assertEqual(completed, 14)
        self.assertEqual(remaining, 4)


if __name__ == "__main__":
    unittest.main()
