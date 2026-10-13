"""Reel video pipeline fields on product_try_ons; provision the fifth AI persona.

Revision ID: 20261010_01
Revises: 20261006_01
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


revision = "20261010_01"
down_revision = "20261006_01"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    sa.Column("media_type", sa.String(20), nullable=False, server_default="image"),
    sa.Column("scene_style", sa.String(50), nullable=True),
    sa.Column("duration_seconds", sa.Integer, nullable=True),
    sa.Column("video_path", sa.String(255), nullable=True),
    sa.Column("video_provider", sa.String(50), nullable=True),
    sa.Column("video_job_id", sa.String(255), nullable=True),
    sa.Column("generation_attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("lease_until", sa.DateTime, nullable=True),
    sa.Column("idempotency_key", sa.String(64), nullable=True),
    sa.Column("storage_status", sa.String(30), nullable=True),
    sa.Column("storage_provider", sa.String(30), nullable=True),
    sa.Column("storage_file_id", sa.String(255), nullable=True),
    sa.Column("storage_error", sa.Text, nullable=True),
    sa.Column("storage_attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("stored_at", sa.DateTime, nullable=True),
    sa.Column("moderation_status", sa.String(30), nullable=True),
]
UNIQUE_NAME = "uq_try_on_merchant_idempotency"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "product_try_ons" in tables:
        existing = {c["name"] for c in inspector.get_columns("product_try_ons")}
        uniques = {u["name"] for u in inspector.get_unique_constraints("product_try_ons")}
        uniques |= {i["name"] for i in inspector.get_indexes("product_try_ons")}
        with op.batch_alter_table("product_try_ons") as batch_op:
            for column in NEW_COLUMNS:
                if column.name not in existing:
                    batch_op.add_column(column.copy())
            if UNIQUE_NAME not in uniques:
                batch_op.create_unique_constraint(UNIQUE_NAME, ["merchant_id", "idempotency_key"])

    if "ai_models" in tables:
        # Imported here so a fresh database (no tables yet) never touches the ORM.
        from app.services.ai_model_roster import ensure_default_ai_models
        session = Session(bind=bind)
        ensure_default_ai_models(session)
        session.flush()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "product_try_ons" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("product_try_ons")}
    uniques = {u["name"] for u in inspector.get_unique_constraints("product_try_ons")}
    uniques |= {i["name"] for i in inspector.get_indexes("product_try_ons")}
    with op.batch_alter_table("product_try_ons") as batch_op:
        if UNIQUE_NAME in uniques:
            batch_op.drop_constraint(UNIQUE_NAME, type_="unique")
        for column in reversed(NEW_COLUMNS):
            if column.name in existing:
                batch_op.drop_column(column.name)
    # The provisioned persona is left in place: reels may reference it.
