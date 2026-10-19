"""extend daily_usage with per-key and token breakdown

Adds key_id granularity and splits total_tokens into prompt/completion so the
usage dashboard can filter by API key and chart tokens without re-reading the
partitioned requests table.

Revision ID: b2c9f14e7a31
Revises: a3773288f007
Create Date: 2026-10-08 21:25:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c9f14e7a31'
down_revision: Union[str, Sequence[str], None] = 'a3773288f007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Recreate daily_usage with key_id and split token columns.

    CREATE MATERIALIZED VIEW ... AS cannot add columns, so the view is dropped
    and rebuilt. It is a pure aggregate, so no data is lost.
    """
    op.execute("DROP MATERIALIZED VIEW IF EXISTS daily_usage;")
    op.execute("""
        CREATE MATERIALIZED VIEW daily_usage AS
        SELECT
            provider,
            model,
            DATE(created_at) AS day,
            MIN(key_id)       AS key_id,
            SUM(tokens_in)    AS tokens_in,
            SUM(tokens_out)   AS tokens_out,
            SUM(tokens_in + tokens_out) AS total_tokens,
            SUM(cost)         AS total_cost,
            COUNT(*)          AS request_count
        FROM requests
        GROUP BY provider, model, DATE(created_at), key_id;
    """)
    # The dashboard aggregates by day; index the common filter paths.
    op.execute("CREATE INDEX IF NOT EXISTS ix_daily_usage_day ON daily_usage (day DESC);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_daily_usage_provider_model "
        "ON daily_usage (provider, model, day DESC);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_usage_key "
        "ON daily_usage (provider, model, day, key_id);"
    )


def downgrade() -> None:
    """Restore the original aggregate shape."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS daily_usage;")
    op.execute("""
        CREATE MATERIALIZED VIEW daily_usage AS
        SELECT
            provider,
            model,
            DATE(created_at) AS day,
            SUM(tokens_in + tokens_out) AS total_tokens,
            SUM(cost) AS total_cost
        FROM requests
        GROUP BY provider, model, DATE(created_at);
    """)