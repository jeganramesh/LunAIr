"""initial schema

Revision ID: a3773288f007
Revises: 
Create Date: 2026-10-08 15:46:28.638741

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3773288f007'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('rpm_limit', sa.Integer(), nullable=False),
        sa.Column('tpm_limit', sa.Integer(), nullable=False),
        sa.Column('monthly_budget_usd', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)

    op.create_table(
        'balance_snapshots',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('balance_usd', sa.Float(), nullable=True),
        sa.Column('lifetime_spend_usd', sa.Float(), nullable=True),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_balance_snapshots_provider'), 'balance_snapshots', ['provider'], unique=False)

    op.create_table(
        'budgets',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('key_id', sa.String(length=64), nullable=True),
        sa.Column('monthly_limit_usd', sa.Float(), nullable=False),
        sa.Column('current_spend_usd', sa.Float(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_budgets_key_id'), 'budgets', ['key_id'], unique=False)

    op.create_table(
        'injection_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('threats', sa.Text(), nullable=False),
        sa.Column('action_taken', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_injection_events_request_id', 'injection_events', ['request_id'], unique=False)

    op.create_table(
        'pii_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('pii_type', sa.String(length=64), nullable=False),
        sa.Column('placeholder', sa.String(length=64), nullable=False),
        sa.Column('location', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pii_events_request_id', 'pii_events', ['request_id'], unique=False)

    op.create_table(
        'requests',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('key_id', sa.String(length=64), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=False),
        sa.Column('tokens_out', sa.Integer(), nullable=False),
        sa.Column('reasoning_tokens', sa.Integer(), nullable=False),
        sa.Column('cached_tokens', sa.Integer(), nullable=False),
        sa.Column('cost', sa.Float(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('ttft_ms', sa.Float(), nullable=True),
        sa.Column('fallback_from', sa.String(length=128), nullable=True),
        sa.Column('pii_redacted', sa.Boolean(), nullable=False),
        sa.Column('injection_blocked', sa.Boolean(), nullable=False),
        sa.Column('cache_hit', sa.Boolean(), nullable=False),
        sa.Column('cache_similarity', sa.Float(), nullable=True),
        sa.Column('gateway_mode', sa.String(length=32), nullable=False),
        sa.Column('finish_reason', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id', 'created_at'),
        postgresql_partition_by='RANGE (created_at)',
    )
    op.create_index('ix_requests_cache_hit', 'requests', ['cache_hit'], unique=False)
    op.create_index('ix_requests_key_id_created_at_desc', 'requests', ['key_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_requests_provider_created_at_desc', 'requests', ['provider', sa.literal_column('created_at DESC')], unique=False)

    # Monthly partitions for requests table
    op.execute("""
        CREATE TABLE IF NOT EXISTS requests_y2026m10 PARTITION OF requests
        FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS requests_y2026m11 PARTITION OF requests
        FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS requests_default PARTITION OF requests DEFAULT;
    """)

    # Materialized view daily_usage
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS daily_usage AS
        SELECT
            provider,
            model,
            DATE(created_at) AS day,
            SUM(tokens_in + tokens_out) AS total_tokens,
            SUM(cost) AS total_cost
        FROM requests
        GROUP BY provider, model, DATE(created_at);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS daily_usage;")
    op.drop_index('ix_requests_provider_created_at_desc', table_name='requests')
    op.drop_index('ix_requests_key_id_created_at_desc', table_name='requests')
    op.drop_index('ix_requests_cache_hit', table_name='requests')
    op.drop_table('requests')
    op.drop_index('ix_pii_events_request_id', table_name='pii_events')
    op.drop_table('pii_events')
    op.drop_index('ix_injection_events_request_id', table_name='injection_events')
    op.drop_table('injection_events')
    op.drop_index(op.f('ix_budgets_key_id'), table_name='budgets')
    op.drop_table('budgets')
    op.drop_index(op.f('ix_balance_snapshots_provider'), table_name='balance_snapshots')
    op.drop_table('balance_snapshots')
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_table('api_keys')
