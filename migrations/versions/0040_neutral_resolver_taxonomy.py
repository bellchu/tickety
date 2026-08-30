"""Replace organization-specific resolver presets with a neutral taxonomy.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GROUPS = (
    "SERVICE_DESK",
    "ENDPOINT_SUPPORT",
    "IDENTITY_ACCESS",
    "NETWORK_OPERATIONS",
    "INFRASTRUCTURE_OPERATIONS",
    "CLOUD_PLATFORM",
    "SECURITY_OPERATIONS",
    "BUSINESS_APPLICATIONS",
    "APPLICATION_OPERATIONS",
    "DATA_SERVICES",
    "INTEGRATION_SERVICES",
    "AUTOMATION_SERVICES",
    "SOFTWARE_ENGINEERING",
    "SERVICE_DELIVERY",
)


def _in_check(column: str) -> str:
    values = ",".join(f"'{group}'" for group in _GROUPS)
    return f"{column} IN ({values})"


def _already_neutral(bind) -> bool:
    expected = (
        ("agent_resolver_team_mappings", "ck_agent_resolver_group_code"),
        (
            "directory_person_resolver_team_mappings",
            "ck_directory_person_resolver_group_code",
        ),
        ("routing_rules", "ck_routing_rule_primary_group"),
        ("routing_rules", "ck_routing_rule_secondary_group"),
    )
    inspector = sa.inspect(bind)
    for table_name, constraint_name in expected:
        constraints = {
            row["name"]: row.get("sqltext") or ""
            for row in inspector.get_check_constraints(table_name)
        }
        if "SERVICE_DESK" not in constraints.get(constraint_name, ""):
            return False
    return True


def upgrade() -> None:
    bind = op.get_bind()
    # Fresh installs already receive the neutral checks from the authoritative
    # table-creation migrations. Do not discard valid data in that case.
    if _already_neutral(bind):
        return

    # The former taxonomy described one organization's ownership model. Its
    # mappings and recommendations cannot be translated safely into neutral
    # teams, so clear them instead of guessing equivalence.
    op.execute(sa.text("DELETE FROM directory_person_resolver_team_audit"))
    op.execute(sa.text("DELETE FROM directory_person_resolver_team_mappings"))
    op.execute(sa.text("DELETE FROM agent_resolver_team_mapping_audit"))
    op.execute(sa.text("DELETE FROM agent_resolver_team_mappings"))
    op.execute(sa.text("DELETE FROM routing_rule_audit"))
    op.execute(sa.text("DELETE FROM routing_rules"))
    op.execute(sa.text(
        "UPDATE tickets SET "
        "ai_suggested_team = NULL, ai_secondary_team = NULL, "
        "ai_routing_confidence = NULL, ai_routing_scope = NULL, "
        "ai_affected_service = NULL, ai_failure_domain = NULL, "
        "ai_routing_reason = NULL, ai_routing_input_hash = NULL"
    ))

    with op.batch_alter_table(
        "agent_resolver_team_mappings", schema=None
    ) as batch_op:
        batch_op.drop_constraint("ck_agent_resolver_group_code", type_="check")
        batch_op.create_check_constraint(
            "ck_agent_resolver_group_code", _in_check("resolver_group")
        )

    with op.batch_alter_table(
        "directory_person_resolver_team_mappings", schema=None
    ) as batch_op:
        batch_op.drop_constraint(
            "ck_directory_person_resolver_group_code", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_directory_person_resolver_group_code",
            _in_check("resolver_group"),
        )

    with op.batch_alter_table("routing_rules", schema=None) as batch_op:
        batch_op.drop_constraint("ck_routing_rule_primary_group", type_="check")
        batch_op.drop_constraint("ck_routing_rule_secondary_group", type_="check")
        batch_op.create_check_constraint(
            "ck_routing_rule_primary_group", _in_check("primary_group")
        )
        batch_op.create_check_constraint(
            "ck_routing_rule_secondary_group",
            "secondary_group IS NULL OR " + _in_check("secondary_group"),
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
