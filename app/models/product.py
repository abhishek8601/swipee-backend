from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import ProductStatus

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    style_code = Column(String(100), nullable=False)

    short_description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    highlights = Column(JSON, nullable=True)

    mrp = Column(Numeric(12, 2), nullable=False)
    selling_price = Column(Numeric(12, 2), nullable=False)
    cost_price = Column(Numeric(12, 2), nullable=True)

    hsn_code = Column(String(12), nullable=True)
    tax_rate = Column(Numeric(5, 2), nullable=True)
    tax_inclusive = Column(Boolean, default=True)

    country_of_origin = Column(String(100), default="India")
    manufacturer_name = Column(String(255), nullable=True)
    manufacturer_address = Column(Text, nullable=True)
    packer_name = Column(String(255), nullable=True)
    packer_address = Column(Text, nullable=True)
    importer_name = Column(String(255), nullable=True)
    importer_address = Column(Text, nullable=True)

    size_chart_id = Column(Integer, ForeignKey("size_charts.id", ondelete="SET NULL"), nullable=True)
    wash_care = Column(Text, nullable=True)
    model_size_note = Column(Text, nullable=True)

    status = Column(String(50), default=ProductStatus.DRAFT.value, index=True)
    rejection_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    merchant = relationship("Merchant", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    category = relationship("Category", back_populates="products")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    attribute_values = relationship("ProductAttributeValue", back_populates="product", cascade="all, delete-orphan")
    approval_history = relationship("ProductApprovalHistory", back_populates="product", cascade="all, delete-orphan")
    try_ons = relationship("ProductTryOn", back_populates="product", cascade="all, delete-orphan")

    @property
    def status_enum(self) -> ProductStatus:
        try:
            return ProductStatus(self.status)
        except ValueError:
            return ProductStatus.DRAFT

    @property
    def status_label(self) -> str:
        return self.status_enum.label

    @property
    def primary_image(self):
        primary = next((img for img in self.images if img.is_primary), None)
        return primary or (self.images[0] if self.images else None)


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), unique=True, index=True, nullable=False)
    barcode = Column(String(100), nullable=True)

    size_attribute_value_id = Column(Integer, ForeignKey("attribute_values.id", ondelete="RESTRICT"), nullable=True)
    colour_attribute_value_id = Column(Integer, ForeignKey("attribute_values.id", ondelete="RESTRICT"), nullable=True)

    mrp = Column(Numeric(12, 2), nullable=True)
    selling_price = Column(Numeric(12, 2), nullable=True)
    cost_price = Column(Numeric(12, 2), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    product = relationship("Product", back_populates="variants")
    size_value = relationship("AttributeValue", foreign_keys=[size_attribute_value_id])
    colour_value = relationship("AttributeValue", foreign_keys=[colour_attribute_value_id])
    inventory = relationship("Inventory", back_populates="variant", cascade="all, delete-orphan")

    @property
    def effective_mrp(self):
        return self.mrp if self.mrp is not None else self.product.mrp

    @property
    def effective_selling_price(self):
        return self.selling_price if self.selling_price is not None else self.product.selling_price


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    colour_attribute_value_id = Column(Integer, ForeignKey("attribute_values.id", ondelete="SET NULL"), nullable=True)
    image_path = Column(String(255), nullable=False)
    thumb_path = Column(String(255), nullable=True)
    is_primary = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="images")
    colour_value = relationship("AttributeValue", foreign_keys=[colour_attribute_value_id])


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(Integer, ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False)
    attribute_value_id = Column(Integer, ForeignKey("attribute_values.id", ondelete="SET NULL"), nullable=True)
    text_value = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="attribute_values")
    attribute = relationship("Attribute")
    value = relationship("AttributeValue")


class ProductApprovalHistory(Base):
    __tablename__ = "product_approval_history"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = Column(String(50), nullable=True)
    to_status = Column(String(50), nullable=False)
    reason = Column(Text, nullable=True)
    action_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="approval_history")
    actor = relationship("User", foreign_keys=[action_by])
