"""Allow reels without an AI model (videos imported from Google Drive).

Revision ID: 20261014_01
Revises: 20261013_01
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa


revision = "20261014_01"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def _nullable(bind) -> bool:
    cols = {c["name"]: c for c in sa.inspect(bind).get_columns("product_try_ons")}
    return bool(cols["ai_model_id"]["nullable"])


def upgrade() -> None:
    bind = op.get_bind()
    if "product_try_ons" not in sa.inspect(bind).get_table_names() or _nullable(bind):
        return
    with op.batch_alter_table("product_try_ons") as batch_op:
        batch_op.alter_column("ai_model_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "product_try_ons" not in sa.inspect(bind).get_table_names() or not _nullable(bind):
        return
    # Imported reels have no AI model and would violate NOT NULL.
    op.execute("DELETE FROM product_try_ons WHERE ai_model_id IS NULL")
    with op.batch_alter_table("product_try_ons") as batch_op:
        batch_op.alter_column("ai_model_id", existing_type=sa.Integer(), nullable=False)
