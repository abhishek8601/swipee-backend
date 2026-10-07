"""Add the buyer registration gender field.

Revision ID: 20261001_01
Revises:
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa


revision = "20261001_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        # This project creates its base tables from SQLAlchemy metadata. There
        # is nothing to upgrade on a fresh database.
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "gender" not in columns:
            batch_op.add_column(sa.Column("gender", sa.String(length=32), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    with op.batch_alter_table("users") as batch_op:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "gender" in columns:
            batch_op.drop_column("gender")
