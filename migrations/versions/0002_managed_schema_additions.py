"""managed schema additions

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12 01:57:44.047531
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    additions = {
        'users': [
            sa.Column('role', sa.String(), nullable=True, server_default=sa.text("'agent'")),
            sa.Column('password_hash', sa.String(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column('last_login_at', sa.DateTime(), nullable=True),
        ],
        'kb_articles': [
            sa.Column('reviewer_id', sa.String(), nullable=True),
            sa.Column('version', sa.Integer(), nullable=True, server_default=sa.text('1')),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('review_due_at', sa.DateTime(), nullable=True),
        ],
        'service_requests': [
            sa.Column('approval_status', sa.String(), nullable=True, server_default=sa.text("'not_required'")),
            sa.Column('fulfillment_status', sa.String(), nullable=True, server_default=sa.text("'pending'")),
            sa.Column('approved_by', sa.String(), nullable=True),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('delivery_notes', sa.Text(), nullable=True),
            sa.Column('fulfilled_by', sa.String(), nullable=True),
            sa.Column('fulfilled_at', sa.DateTime(), nullable=True),
        ],
        'tickets': [
            sa.Column('ticket_type', sa.String(), nullable=True, server_default=sa.text("'incident'")),
            sa.Column('impact', sa.String(), nullable=True),
            sa.Column('urgency', sa.String(), nullable=True),
            sa.Column('workflow_status', sa.String(), nullable=True, server_default=sa.text("'New'")),
            sa.Column('ai_review_state', sa.String(), nullable=True),
            sa.Column('assignee_id', sa.String(), nullable=True),
            sa.Column('service_id', sa.String(), nullable=True),
            sa.Column('asset_id', sa.String(), nullable=True),
            sa.Column('response_due_at', sa.DateTime(), nullable=True),
            sa.Column('resolution_due_at', sa.DateTime(), nullable=True),
            sa.Column('due_by', sa.DateTime(), nullable=True),
            sa.Column('sla_paused_at', sa.DateTime(), nullable=True),
            sa.Column('sla_paused_seconds', sa.Integer(), nullable=True, server_default=sa.text('0')),
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('portal_access_token_hash', sa.String(length=64), nullable=True),
            sa.Column('portal_access_expires_at', sa.DateTime(), nullable=True),
            sa.Column('external_workspace_id', sa.String(), nullable=True),
            sa.Column('external_created_at', sa.DateTime(), nullable=True),
            sa.Column('external_resolved_at', sa.DateTime(), nullable=True),
            sa.Column('external_due_by', sa.DateTime(), nullable=True),
            sa.Column('external_fr_due_by', sa.DateTime(), nullable=True),
            sa.Column('escalation_risk', sa.Integer(), nullable=True, server_default=sa.text('0')),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('recommended_solution', sa.Text(), nullable=True),
        ],
    }

    for table_name, columns in additions.items():
        existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table_name, column)

    inspector = sa.inspect(op.get_bind())
    ticket_indexes = {index['name']: index for index in inspector.get_indexes('tickets')}
    expected_indexes = {
        'ix_tickets_assignee_id': (['assignee_id'], False),
        'ix_tickets_portal_access_token_hash': (['portal_access_token_hash'], True),
    }
    for name, (columns, unique) in expected_indexes.items():
        existing = ticket_indexes.get(name)
        if existing:
            if existing['column_names'] != columns or bool(existing.get('unique')) != unique:
                raise RuntimeError(f'Existing index {name} does not match the managed schema')
        else:
            op.create_index(name, 'tickets', columns, unique=unique)

    foreign_keys = {
        'kb_articles': [
            ('fk_kb_articles_reviewer_id_users', ['reviewer_id'], 'users', ['id']),
        ],
        'service_requests': [
            ('fk_service_requests_approved_by_users', ['approved_by'], 'users', ['id']),
            ('fk_service_requests_fulfilled_by_users', ['fulfilled_by'], 'users', ['id']),
        ],
        'tickets': [
            ('fk_tickets_assignee_id_users', ['assignee_id'], 'users', ['id']),
        ],
    }
    for table_name, expected in foreign_keys.items():
        existing = sa.inspect(op.get_bind()).get_foreign_keys(table_name)
        missing = [
            item for item in expected
            if not any(
                fk['constrained_columns'] == item[1]
                and fk['referred_table'] == item[2]
                and fk['referred_columns'] == item[3]
                for fk in existing
            )
        ]
        if missing:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                for name, local_columns, remote_table, remote_columns in missing:
                    batch_op.create_foreign_key(name, remote_table, local_columns, remote_columns)


def downgrade() -> None:
    raise RuntimeError(
        'Tickety migrations are forward-only; restore a verified backup or apply a forward fix.'
    )
