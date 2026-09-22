"""Fence pre-recovery SSO states with a durable authentication epoch."""

from alembic import op
import sqlalchemy as sa


revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


_EPOCH_TABLE = "auth_security_epoch"
_EPOCH_COLUMNS = {"singleton_id", "epoch", "updated_at"}
_EPOCH_SINGLETON_CHECK = "ck_auth_security_epoch_singleton"
_EPOCH_NONNEGATIVE_CHECK = "ck_auth_security_epoch_nonnegative"
_MAX_SIGNED_BIGINT = 9_223_372_036_854_775_807


def _normalized_sql(value) -> str:
    normalized = "".join(str(value or "").lower().split())
    normalized = normalized.replace('"', "").replace("'", "")
    normalized = normalized.replace("::bigint", "").replace("::integer", "")
    return normalized.replace("(", "").replace(")", "")


def _has_zero_default(column) -> bool:
    return _normalized_sql(column.get("default")) == "0"


def _is_compatible_epoch_type(column, dialect_name: str) -> bool:
    column_type = column["type"]
    if dialect_name == "postgresql":
        return isinstance(column_type, sa.BigInteger)
    # SQLite stores signed integer values in 64 bits regardless of the
    # reflected spelling (INTEGER/BIGINT), so either integer affinity is safe.
    return isinstance(column_type, sa.Integer)


def _require_epoch_column(inspector, table_name: str, column_name: str, bind) -> None:
    columns = {
        column["name"]: column for column in inspector.get_columns(table_name)
    }
    column = columns.get(column_name)
    if (
        not column
        or column.get("nullable")
        or not _is_compatible_epoch_type(column, bind.dialect.name)
        or not _has_zero_default(column)
    ):
        raise RuntimeError(
            f"{table_name}.{column_name} is incompatible; apply a forward repair"
        )


def _ensure_epoch_column(table_name: str, column_name: str, bind) -> None:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        raise RuntimeError(f"{table_name} is missing; restore a verified backup")
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in existing:
        op.add_column(
            table_name,
            sa.Column(
                column_name,
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        inspector = sa.inspect(bind)
    _require_epoch_column(inspector, table_name, column_name, bind)


def _ensure_epoch_table(bind) -> None:
    inspector = sa.inspect(bind)
    if _EPOCH_TABLE not in inspector.get_table_names():
        op.create_table(
            _EPOCH_TABLE,
            sa.Column("singleton_id", sa.Integer(), primary_key=True),
            sa.Column(
                "epoch",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            # Runtime and the seed below explicitly write this timestamp.  Do
            # not add a server default: the ORM bootstrap deliberately has no
            # one, and both schema creation paths must remain equivalent.
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("singleton_id = 1", name=_EPOCH_SINGLETON_CHECK),
            sa.CheckConstraint("epoch >= 0", name=_EPOCH_NONNEGATIVE_CHECK),
        )
        inspector = sa.inspect(bind)

    columns = {
        column["name"]: column for column in inspector.get_columns(_EPOCH_TABLE)
    }
    if set(columns) != _EPOCH_COLUMNS:
        raise RuntimeError("authentication security epoch schema is incompatible; apply a forward repair")
    singleton = columns["singleton_id"]
    epoch = columns["epoch"]
    updated_at = columns["updated_at"]
    if (
        singleton.get("nullable")
        or not isinstance(singleton["type"], sa.Integer)
        or epoch.get("nullable")
        or not _is_compatible_epoch_type(epoch, bind.dialect.name)
        or not _has_zero_default(epoch)
        or updated_at.get("nullable")
        or not isinstance(updated_at["type"], sa.DateTime)
    ):
        raise RuntimeError("authentication security epoch schema is incompatible; apply a forward repair")
    if inspector.get_pk_constraint(_EPOCH_TABLE).get("constrained_columns") != ["singleton_id"]:
        raise RuntimeError("authentication security epoch primary key is incompatible; apply a forward repair")
    checks = {
        check["name"]: _normalized_sql(check.get("sqltext"))
        for check in inspector.get_check_constraints(_EPOCH_TABLE)
    }
    if (
        checks.get(_EPOCH_SINGLETON_CHECK) != "singleton_id=1"
        or checks.get(_EPOCH_NONNEGATIVE_CHECK) != "epoch>=0"
    ):
        raise RuntimeError("authentication security epoch checks are incompatible; apply a forward repair")


def _seed_and_validate_epoch(bind) -> int:
    bind.execute(sa.text(
        "INSERT INTO auth_security_epoch (singleton_id, epoch, updated_at) "
        "VALUES (1, 0, CURRENT_TIMESTAMP) "
        "ON CONFLICT (singleton_id) DO NOTHING"
    ))
    rows = bind.execute(sa.text(
        "SELECT singleton_id, epoch FROM auth_security_epoch ORDER BY singleton_id"
    )).all()
    if len(rows) != 1 or rows[0][0] != 1:
        raise RuntimeError("authentication security epoch seed is incompatible; apply a forward repair")
    epoch = rows[0][1]
    if isinstance(epoch, bool) or not isinstance(epoch, int):
        raise RuntimeError(
            "authentication security epoch seed is incompatible; apply a forward repair"
        )
    if epoch < 0 or epoch > _MAX_SIGNED_BIGINT:
        raise RuntimeError("authentication security epoch seed is incompatible; apply a forward repair")
    return epoch


def _validate_user_lower_bounds(bind, current_epoch: int) -> None:
    rows = bind.execute(sa.text(
        "SELECT id, auth_not_before_epoch FROM users ORDER BY id"
    )).all()
    for user_id, lower_bound in rows:
        if (
            isinstance(lower_bound, bool)
            or not isinstance(lower_bound, int)
            or lower_bound < 0
            or lower_bound > current_epoch
        ):
            raise RuntimeError(
                "user authentication epoch lower bound is incompatible; apply a forward repair"
            )


def _cut_over_authentication(bind, current_epoch: int) -> None:
    if current_epoch >= _MAX_SIGNED_BIGINT:
        raise RuntimeError(
            "authentication security epoch is exhausted; restore a verified backup or apply a forward repair"
        )
    next_epoch = current_epoch + 1
    updated = bind.execute(sa.text(
        "UPDATE auth_security_epoch "
        "SET epoch = :next_epoch, updated_at = CURRENT_TIMESTAMP "
        "WHERE singleton_id = 1 AND epoch = :current_epoch"
    ), {"next_epoch": next_epoch, "current_epoch": current_epoch})
    if updated.rowcount != 1:
        raise RuntimeError(
            "authentication security epoch changed during cutover; retry with all API replicas stopped"
        )

    # 0056 establishes a durable revocation boundary.  The deployment gate
    # stops legacy API replicas first, then this transaction removes every
    # pre-cutover browser session and OIDC state before a new replica starts.
    bind.execute(sa.text(
        "UPDATE users SET auth_not_before_epoch = :next_epoch"
    ), {"next_epoch": next_epoch})
    bind.execute(sa.text("DELETE FROM sso_transactions"))
    bind.execute(sa.text("DELETE FROM sessions"))


def upgrade():
    bind = op.get_bind()
    _ensure_epoch_column("users", "auth_not_before_epoch", bind)
    _ensure_epoch_column("sso_transactions", "auth_epoch", bind)
    _ensure_epoch_table(bind)
    current_epoch = _seed_and_validate_epoch(bind)
    _validate_user_lower_bounds(bind, current_epoch)
    _cut_over_authentication(bind, current_epoch)


def downgrade():
    raise RuntimeError(
        "SSO recovery epoch fencing is forward-only; restore a verified backup or apply a forward fix."
    )
