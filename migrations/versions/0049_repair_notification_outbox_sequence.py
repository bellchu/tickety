"""Monotonically recover a stale notification dispatch sequence."""
from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "notification_outbox" not in inspector.get_table_names():
        raise RuntimeError("notification outbox is missing; restore a verified backup")
    if "notification_outbox_sequence" not in inspector.get_table_names():
        raise RuntimeError("notification outbox sequence is missing; restore a verified backup")

    # The singleton row is deliberately updated only upward.  PostgreSQL
    # locks this row while the migration transaction runs, so a producer that
    # starts after schema verification observes the repaired value; SQLite's
    # write transaction provides the matching demo/test behavior.
    repaired = connection.execute(
        sa.text(
            "UPDATE notification_outbox_sequence "
            "SET next_dispatch_order = ("
            "SELECT COALESCE(MAX(dispatch_order), 0) FROM notification_outbox"
            ") "
            "WHERE singleton_id = 1 "
            "AND next_dispatch_order < ("
            "SELECT COALESCE(MAX(dispatch_order), 0) FROM notification_outbox"
            ")"
        )
    )
    if repaired.rowcount not in (0, 1):
        raise RuntimeError("notification outbox sequence seed is incompatible; apply a forward repair")

    rows = connection.execute(
        sa.text(
            "SELECT singleton_id, next_dispatch_order "
            "FROM notification_outbox_sequence ORDER BY singleton_id"
        )
    ).all()
    if len(rows) != 1 or rows[0][0] != 1:
        raise RuntimeError("notification outbox sequence seed is incompatible; apply a forward repair")


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
