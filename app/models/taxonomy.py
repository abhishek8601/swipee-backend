from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean, DateTime, ForeignKey, Table, JSON
)
from sqlalchemy.orm import relationship
from app.core.database import Base

attribute_category = Table(
    "attribute_category",
    Base.metadata,
    Column("attribute_id", Integer, ForeignKey("attributes.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)

brand_merchant = Table(
    "brand_merchant",
    Base.metadata,
    Column("brand_id", Integer, ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True),
    Column("merchant_id", Integer, ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True),
    Column("status", String(50), default="approved"),
)

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    image_path = Column(String(255), nullable=True)
    icon = Column(String(100), nullable=True)

    path = Column(String(255), nullable=True, index=True)
    level = Column(Integer, default=0)
    is_leaf = Column(Boolean, default=True)

    commission_rate = Column(Numeric(5, 2), nullable=True)
    tax_rate = Column(Numeric(5, 2), nullable=True)
    hsn_code = Column(String(12), nullable=True)

    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    meta_title = Column(String(255), nullable=True)
    meta_description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    parent = relationship("Category", remote_side=[id], back_populates="children")
    children = relationship("Category", back_populates="parent", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="category")
    attributes = relationship("Attribute", secondary=attribute_category, back_populates="categories")


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    logo_path = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    website = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(String(50), default="approved")  # approved, pending, rejected
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    products = relationship("Product", back_populates="brand")


class Attribute(Base):
    __tablename__ = "attributes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(100), unique=True, index=True, nullable=False)
    type = Column(String(50), default="text")  # text, select, multiselect, boolean, number
    is_required = Column(Boolean, default=False)
    is_filterable = Column(Boolean, default=True)
    is_variant_axis = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    values = relationship("AttributeValue", back_populates="attribute", cascade="all, delete-orphan")
    categories = relationship("Category", secondary=attribute_category, back_populates="attributes")


class AttributeValue(Base):
    __tablename__ = "attribute_values"

    id = Column(Integer, primary_key=True, index=True)
    attribute_id = Column(Integer, ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    hex_color = Column(String(10), nullable=True)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    attribute = relationship("Attribute", back_populates="values")


class SizeChart(Base):
    __tablename__ = "size_charts"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
