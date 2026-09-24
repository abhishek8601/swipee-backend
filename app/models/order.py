from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(40), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)

    status = Column(String(50), default="pending", index=True)

    items_subtotal = Column(Numeric(14, 2), default=0.00)
    discount_total = Column(Numeric(14, 2), default=0.00)
    tax_total = Column(Numeric(14, 2), default=0.00)
    shipping_total = Column(Numeric(14, 2), default=0.00)
    grand_total = Column(Numeric(14, 2), default=0.00)
    currency = Column(String(3), default="INR")

    coupon_code = Column(String(50), nullable=True)

    payment_method = Column(String(50), nullable=True)
    payment_status = Column(String(50), default="pending")
    payment_reference = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)

    shipping_name = Column(String(255), nullable=True)
    shipping_phone = Column(String(20), nullable=True)
    shipping_address_line1 = Column(String(255), nullable=True)
    shipping_address_line2 = Column(String(255), nullable=True)
    shipping_city = Column(String(100), nullable=True)
    shipping_state = Column(String(100), nullable=True)
    shipping_postal_code = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    product_variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)

    product_name = Column(String(255), nullable=False)
    variant_sku = Column(String(100), nullable=False)
    size_name = Column(String(50), nullable=True)
    colour_name = Column(String(50), nullable=True)

    quantity = Column(Integer, default=1, nullable=False)
    mrp = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0.00)
    tax_amount = Column(Numeric(12, 2), default=0.00)
    discount_amount = Column(Numeric(12, 2), default=0.00)
    total_amount = Column(Numeric(12, 2), nullable=False)

    commission_rate = Column(Numeric(5, 2), default=15.00)
    commission_amount = Column(Numeric(12, 2), default=0.00)

    status = Column(String(50), default="pending", index=True)  # pending, confirmed, processing, shipped, delivered, cancelled, returned
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order", back_populates="items")
    merchant = relationship("Merchant")
    product = relationship("Product")
    variant = relationship("ProductVariant")
    warehouse = relationship("Warehouse")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    status = Column(String(50), default="created")
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order", back_populates="shipments")


class Return(Base):
    __tablename__ = "returns"

    id = Column(Integer, primary_key=True, index=True)
    order_item_id = Column(Integer, ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(50), default="requested")
    refund_amount = Column(Numeric(12, 2), default=0.00)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order_item = relationship("OrderItem")
