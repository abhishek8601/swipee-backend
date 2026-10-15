"""Password reset codes (forgot-password by emailed 6-digit code).

Revision ID: 20261013_01
Revises: 20261010_01
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa


revision = "20261013_01"
down_revision = "20261010_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "password_reset_codes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("requested_ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_password_reset_codes_id", "password_reset_codes", ["id"])
    op.create_index("ix_password_reset_codes_user_id", "password_reset_codes", ["user_id"])


def downgrade() -> None:
    if "password_reset_codes" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("password_reset_codes")
