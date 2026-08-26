import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.ai_eligibility import is_terminal_status, terminal_ticket_filter
from app.backend.database import (
    Base,
    TicketPriorityConfigRecord,
    TicketRecord,
    TicketStatusConfigRecord,
)
from app.backend.portable_keys import (
    portable_ascii_lower,
    portable_ascii_lower_expression,
)
from app.backend.sla_policy import sla_eligible_filter, ticket_is_sla_exempt


class PortableTicketKeyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_ascii_normalization_preserves_non_ascii_characters_in_python_and_sql(self):
        priorities = {
            "ascii-upper": "K",
            "kelvin-sign": "K",
            "dotted-capital-i": "İ",
            "accented-capital-e": "É",
        }
        expected = {
            "ascii-upper": "k",
            "kelvin-sign": "K",
            "dotted-capital-i": "İ",
            "accented-capital-e": "É",
        }
        with self.session_factory() as db:
            for ticket_id, priority in priorities.items():
                db.add(TicketRecord(
                    id=ticket_id,
                    subject=ticket_id,
                    status="Open",
                    priority=priority,
                ))
            db.commit()
            sql_values = dict(db.query(
                TicketRecord.id,
                portable_ascii_lower_expression(TicketRecord.priority),
            ).all())

        self.assertEqual(sql_values, expected)
        self.assertEqual(
            {key: portable_ascii_lower(value) for key, value in priorities.items()},
            expected,
        )

    def test_priority_status_and_sla_policies_share_the_portable_contract(self):
        with self.session_factory() as db:
            for key in ("k", "i", "e"):
                db.add(TicketPriorityConfigRecord(
                    name=key,
                    name_key=key,
                    label=key,
                    weight=1,
                ))
                db.add(TicketStatusConfigRecord(
                    name=key,
                    name_key=key,
                    label=key,
                    is_open=False,
                    is_terminal=True,
                ))
            values = {
                "ascii": "K",
                "kelvin": "K",
                "dotted-i": "İ",
                "accented-e": "É",
            }
            for ticket_id, value in values.items():
                db.add(TicketRecord(
                    id=ticket_id,
                    subject=ticket_id,
                    status=value,
                    workflow_status="Open",
                    external_status="Open",
                    priority=value,
                ))
            db.commit()

            weights = dict(db.query(
                TicketRecord.id,
                main._priority_weight_expression(),
            ).all())
            terminal_ids = {
                row.id
                for row in db.query(TicketRecord).filter(terminal_ticket_filter(db)).all()
            }
            sla_eligible_ids = {
                row.id
                for row in db.query(TicketRecord).filter(
                    sla_eligible_filter({"k", "i", "e"})
                ).all()
            }
            python_terminal = {
                ticket_id
                for ticket_id, value in values.items()
                if is_terminal_status(db, value)
            }
            python_sla_eligible = {
                ticket_id
                for ticket_id in values
                if not ticket_is_sla_exempt(
                    db.get(TicketRecord, ticket_id),
                    {"k", "i", "e"},
                )
            }

        self.assertEqual(weights, {
            "ascii": 1,
            "kelvin": 1_000,
            "dotted-i": 1_000,
            "accented-e": 1_000,
        })
        self.assertEqual(terminal_ids, {"ascii"})
        self.assertEqual(python_terminal, terminal_ids)
        self.assertEqual(sla_eligible_ids, {"kelvin", "dotted-i", "accented-e"})
        self.assertEqual(python_sla_eligible, sla_eligible_ids)


if __name__ == "__main__":
    unittest.main()
