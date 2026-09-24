from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, column_property
from app.core.database import Base
from app.core.enums import MovementType

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False)
    contact_person = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)

    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(100), default="India")

    is_primary = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    merchant = relationship("Merchant", back_populates="warehouses")
    inventories = relationship("Inventory", back_populates="warehouse", cascade="all, delete-orphan")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    product_variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)

    on_hand = Column(Integer, default=0, nullable=False)
    reserved = Column(Integer, default=0, nullable=False)

    # Computed column property: on_hand - reserved
    available = column_property(on_hand - reserved)

    low_stock_threshold = Column(Integer, default=5)
    safety_stock = Column(Integer, default=0)

    last_counted_at = Column(DateTime, nullable=True)
    last_movement_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_variant_id", "warehouse_id", name="inventory_variant_warehouse_unique"),
        Index("ix_inventory_warehouse_available", "warehouse_id"),
    )

    variant = relationship("ProductVariant", back_populates="inventory")
    warehouse = relationship("Warehouse", back_populates="inventories")
    movements = relationship("InventoryMovement", back_populates="inventory", cascade="all, delete-orphan")

    @property
    def is_low_stock(self) -> bool:
        return (self.on_hand - self.reserved) <= self.low_stock_threshold


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventory.id", ondelete="CASCADE"), nullable=False, index=True)
    product_variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String(50), nullable=False)  # MovementType value
    affects = Column(String(20), default="on_hand", nullable=False)  # on_hand or reserved

    quantity_change = Column(Integer, nullable=False)
    on_hand_after = Column(Integer, nullable=False)
    reserved_after = Column(Integer, nullable=False)

    reference_type = Column(String(100), nullable=True)
    reference_id = Column(Integer, nullable=True)

    reason = Column(Text, nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    inventory = relationship("Inventory", back_populates="movements")
    variant = relationship("ProductVariant")
    warehouse = relationship("Warehouse")
    merchant = relationship("Merchant")
    actor = relationship("User", foreign_keys=[actor_id])

    @property
    def type_enum(self) -> MovementType:
        try:
            return MovementType(self.type)
        except ValueError:
            return MovementType.ADJUSTMENT
