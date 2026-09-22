"""Index bounded recipient-scoped notification reconnect replay."""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    indexes = {
        index["name"]: index
        for index in sa.inspect(connection).get_indexes("notification_outbox")
    }
    existing = indexes.get("ix_notification_outbox_recipient_dispatch_order")
    if existing:
        if existing.get("column_names") != ["recipient_user_id", "dispatch_order"]:
            raise RuntimeError("notification outbox replay index is incompatible; apply a forward repair")
        return
    op.create_index(
        "ix_notification_outbox_recipient_dispatch_order",
        "notification_outbox",
        ["recipient_user_id", "dispatch_order"],
        unique=False,
    )


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
