"""PostgreSQL-only proof for the durable outbox's commit-order lock."""
import os
import unittest

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.backend import main
from app.backend.database import (
    NotificationOutboxSequenceRecord,
    SessionLocal,
    engine,
)


@unittest.skipUnless(
    engine.dialect.name == "postgresql"
    and os.getenv("TICKETY_POSTGRES_INTEGRATION_TESTS") == "true",
    "requires an explicitly enabled PostgreSQL integration database",
)
class NotificationOutboxPostgresIntegrationTests(unittest.TestCase):
    """Keep this separate from SQLite tests: SQLite ignores FOR UPDATE locks."""

    def setUp(self):
        self._reset_outbox_state()

    def tearDown(self):
        self._reset_outbox_state()

    @staticmethod
    def _reset_outbox_state():
        """Return the dedicated CI database tables to an empty known state."""
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM notification_outbox"))
            result = db.execute(text(
                "UPDATE notification_outbox_sequence "
                "SET next_dispatch_order = 0 WHERE singleton_id = 1"
            ))
            if result.rowcount != 1:
                raise AssertionError("notification outbox sequence singleton is missing")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def test_uncommitted_allocation_blocks_a_second_session_until_commit(self):
        first = SessionLocal()
        blocked = SessionLocal()
        after_commit = SessionLocal()
        try:
            self.assertEqual(main._allocate_notification_dispatch_order(first), 1)
            # Flush the increment but deliberately retain the transaction and
            # its SELECT FOR UPDATE lock. A second real PostgreSQL session
            # must not obtain a later dispatch order before this commits.
            first.flush()

            blocked.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with self.assertRaises(OperationalError) as raised:
                main._allocate_notification_dispatch_order(blocked)
            self.assertEqual(getattr(raised.exception.orig, "pgcode", None), "55P03")
            blocked.rollback()

            first.commit()
            self.assertEqual(main._allocate_notification_dispatch_order(after_commit), 2)
            after_commit.commit()

            verification = SessionLocal()
            try:
                sequence = verification.get(NotificationOutboxSequenceRecord, 1)
                self.assertIsNotNone(sequence)
                self.assertEqual(sequence.next_dispatch_order, 2)
            finally:
                verification.close()
        finally:
            first.rollback()
            blocked.rollback()
            after_commit.rollback()
            first.close()
            blocked.close()
            after_commit.close()


if __name__ == "__main__":
    unittest.main()
