"""Add buyer profile, wishlist, cart, address, and size preference storage."""
from alembic import op
import sqlalchemy as sa

revision = "20261006_01"
down_revision = "20261001_01"
branch_labels = None
depends_on = None

def upgrade():
    # Fresh deployments create these tables from SQLAlchemy metadata. Existing
    # deployments should run this revision after resolving the phone migration.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    definitions = {
        "body_profiles": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("measurements", sa.JSON, nullable=False), sa.Column("source", sa.String(30), nullable=False), sa.Column("camera_status", sa.String(30), nullable=False), sa.Column("is_confirmed", sa.Boolean, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime)],
        "wishlist_items": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False), sa.Column("created_at", sa.DateTime), sa.UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product")],
        "carts": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime)],
        "cart_items": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("cart_id", sa.Integer, sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False), sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False), sa.Column("variant_id", sa.Integer, sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False), sa.Column("quantity", sa.Integer, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime), sa.UniqueConstraint("cart_id", "variant_id", name="uq_cart_variant")],
        "user_addresses": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("full_name", sa.String(255), nullable=False), sa.Column("phone", sa.String(20), nullable=False), sa.Column("address_line1", sa.String(255), nullable=False), sa.Column("address_line2", sa.String(255)), sa.Column("city", sa.String(100), nullable=False), sa.Column("state", sa.String(100), nullable=False), sa.Column("postal_code", sa.String(20), nullable=False), sa.Column("country", sa.String(100)), sa.Column("is_default", sa.Boolean, nullable=False), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime)],
        "size_preferences": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("merchant_id", sa.Integer, sa.ForeignKey("merchants.id", ondelete="CASCADE")), sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="CASCADE")), sa.Column("preferred_size", sa.String(50), nullable=False), sa.Column("fit_preference", sa.String(30)), sa.UniqueConstraint("user_id", "merchant_id", "category_id", name="uq_size_preference_scope")],
    }
    for name, columns in definitions.items():
        if name not in existing:
            op.create_table(name, *columns)

def downgrade():
    for table in ("size_preferences", "user_addresses", "cart_items", "carts", "wishlist_items", "body_profiles"): op.drop_table(table)
