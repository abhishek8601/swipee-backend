from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class BodyProfile(Base):
    __tablename__ = "body_profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    measurements = Column(JSON, nullable=False, default=dict)
    source = Column(String(30), nullable=False, default="manual")
    camera_status = Column(String(30), nullable=False, default="not_used")
    is_confirmed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),)
    product = relationship("Product")


class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items = relationship("CartItem", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("cart_id", "variant_id", name="uq_cart_variant"),)
    product = relationship("Product")
    variant = relationship("ProductVariant")


class UserAddress(Base):
    __tablename__ = "user_addresses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(255), nullable=False); phone = Column(String(20), nullable=False)
    address_line1 = Column(String(255), nullable=False); address_line2 = Column(String(255))
    city = Column(String(100), nullable=False); state = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False); country = Column(String(100), default="India")
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow); updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SizePreference(Base):
    __tablename__ = "size_preferences"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE")); category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"))
    preferred_size = Column(String(50), nullable=False); fit_preference = Column(String(30))
    __table_args__ = (UniqueConstraint("user_id", "merchant_id", "category_id", name="uq_size_preference_scope"),)
