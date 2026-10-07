"""Require unique phone numbers for users.

Revision ID: 20261001_02
Revises: 20261001_01
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa


revision = "20261001_02"
down_revision = "20261006_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "phone" not in columns:
        raise RuntimeError("The users table has no phone column; apply the base schema before this migration.")

    missing_phone_count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE phone IS NULL OR TRIM(phone) = ''"
    )).scalar_one()
    if missing_phone_count:
        raise RuntimeError(
            "Cannot require unique user phone numbers while users with blank phone values exist. "
            "Populate those phone values, then run this migration again."
        )

    duplicate_phone = bind.execute(sa.text(
        "SELECT phone FROM users GROUP BY phone HAVING COUNT(*) > 1 LIMIT 1"
    )).scalar_one_or_none()
    if duplicate_phone is not None:
        raise RuntimeError(
            "Cannot add the unique user phone constraint while duplicate phone values exist. "
            "Resolve duplicates, then run this migration again."
        )

    unique_column_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("users")
    }
    unique_column_sets.update(
        tuple(index["column_names"])
        for index in inspector.get_indexes("users")
        if index.get("unique")
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=False)
        if ("phone",) not in unique_column_sets:
            batch_op.create_unique_constraint("uq_users_phone", ["phone"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    with op.batch_alter_table("users") as batch_op:
        constraints = {c["name"] for c in inspector.get_unique_constraints("users")}
        if "uq_users_phone" in constraints:
            batch_op.drop_constraint("uq_users_phone", type_="unique")
        batch_op.alter_column("phone", existing_type=sa.String(length=20), nullable=True)
