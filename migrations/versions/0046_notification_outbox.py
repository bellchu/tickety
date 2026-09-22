"""Persist commit-ordered realtime notifications for independent API replicas."""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "notification_outbox" in inspector.get_table_names():
        expected = {
            "id", "dispatch_order", "recipient_user_id", "event_type", "payload_json",
            "dedupe_key", "created_at", "expires_at",
        }
        actual = {column["name"] for column in inspector.get_columns("notification_outbox")}
        if actual != expected:
            raise RuntimeError("notification outbox schema is incompatible; apply a forward repair")
        primary_key = inspector.get_pk_constraint("notification_outbox")
        if primary_key.get("constrained_columns") != ["id"]:
            raise RuntimeError("notification outbox primary key is incompatible; apply a forward repair")
        unique_constraints = {
            item["name"]: item for item in inspector.get_unique_constraints("notification_outbox")
        }
        dedupe = unique_constraints.get("uq_notification_outbox_dedupe_key")
        if not dedupe or dedupe.get("column_names") != ["dedupe_key"]:
            raise RuntimeError("notification outbox dedupe constraint is incompatible; apply a forward repair")
        dispatch_order = unique_constraints.get("uq_notification_outbox_dispatch_order")
        if not dispatch_order or dispatch_order.get("column_names") != ["dispatch_order"]:
            raise RuntimeError("notification outbox dispatch-order constraint is incompatible; apply a forward repair")
        indexes = {item["name"]: item for item in inspector.get_indexes("notification_outbox")}
        expected_indexes = {
            "ix_notification_outbox_dispatch_order": ["dispatch_order"],
            "ix_notification_outbox_recipient_id": ["recipient_user_id", "id"],
            "ix_notification_outbox_expires_at_id": ["expires_at", "id"],
        }
        if any(
            name not in indexes or indexes[name].get("column_names") != columns
            for name, columns in expected_indexes.items()
        ):
            raise RuntimeError("notification outbox indexes are incompatible; apply a forward repair")
    else:
        op.create_table(
            "notification_outbox",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dispatch_order", sa.BigInteger(), nullable=False),
            sa.Column("recipient_user_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe_key"),
            sa.UniqueConstraint("dispatch_order", name="uq_notification_outbox_dispatch_order"),
        )
        op.create_index(
            "ix_notification_outbox_dispatch_order", "notification_outbox",
            ["dispatch_order"], unique=False,
        )
        op.create_index(
            "ix_notification_outbox_recipient_id", "notification_outbox",
            ["recipient_user_id", "id"], unique=False,
        )
        op.create_index(
            "ix_notification_outbox_expires_at_id", "notification_outbox",
            ["expires_at", "id"], unique=False,
        )

    inspector = sa.inspect(connection)
    if "notification_outbox_sequence" not in inspector.get_table_names():
        op.create_table(
            "notification_outbox_sequence",
            sa.Column("singleton_id", sa.Integer(), primary_key=True),
            sa.Column("next_dispatch_order", sa.BigInteger(), nullable=False),
        )
        connection.execute(
            sa.text(
                "INSERT INTO notification_outbox_sequence "
                "(singleton_id, next_dispatch_order) "
                "SELECT 1, COALESCE(MAX(dispatch_order), 0) "
                "FROM notification_outbox"
            )
        )
        return

    sequence_columns = {
        column["name"] for column in inspector.get_columns("notification_outbox_sequence")
    }
    if sequence_columns != {"singleton_id", "next_dispatch_order"}:
        raise RuntimeError("notification outbox sequence schema is incompatible; apply a forward repair")
    sequence_pk = inspector.get_pk_constraint("notification_outbox_sequence")
    if sequence_pk.get("constrained_columns") != ["singleton_id"]:
        raise RuntimeError("notification outbox sequence primary key is incompatible; apply a forward repair")
    sequence_rows = connection.execute(
        sa.text(
            "SELECT singleton_id, next_dispatch_order "
            "FROM notification_outbox_sequence ORDER BY singleton_id"
        )
    ).all()
    if not sequence_rows:
        max_dispatch_order = connection.execute(
            sa.text("SELECT COALESCE(MAX(dispatch_order), 0) FROM notification_outbox")
        ).scalar_one()
        connection.execute(
            sa.text(
                "INSERT INTO notification_outbox_sequence "
                "(singleton_id, next_dispatch_order) VALUES (1, :next_order)"
            ),
            {"next_order": int(max_dispatch_order)},
        )
        return
    if len(sequence_rows) != 1 or sequence_rows[0][0] != 1:
        raise RuntimeError("notification outbox sequence seed is incompatible; apply a forward repair")
    max_dispatch_order = connection.execute(
        sa.text("SELECT COALESCE(MAX(dispatch_order), 0) FROM notification_outbox")
    ).scalar_one()
    if int(sequence_rows[0][1]) < int(max_dispatch_order):
        # This migration can encounter a relation created by an interrupted
        # compatibility bootstrap.  Raising here would strand the database
        # before later recovery migrations run, while allocating from the
        # stale value makes the unique dispatch-order invariant fail.  The
        # migration transaction serializes this monotonic repair before any
        # application replica is allowed to use the schema.
        connection.execute(
            sa.text(
                "UPDATE notification_outbox_sequence "
                "SET next_dispatch_order = :next_order "
                "WHERE singleton_id = 1 AND next_dispatch_order < :next_order"
            ),
            {"next_order": int(max_dispatch_order)},
        )


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
