from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, DateTime, ForeignKey, Boolean
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import MerchantStatus

class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True, index=True)
    legal_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=False)

    logo_path = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    website = Column(String(255), nullable=True)

    business_type = Column(String(50), default="proprietorship")
    gstin = Column(String(15), unique=True, nullable=True)
    pan = Column(String(10), nullable=True)
    cin = Column(String(21), nullable=True)

    status = Column(String(50), default=MerchantStatus.PENDING.value, index=True)
    status_reason = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    onboarded_at = Column(DateTime, nullable=True)

    default_commission_rate = Column(Numeric(5, 2), default=15.00)
    payout_cycle = Column(String(20), default="weekly")
    settlement_days = Column(Integer, default=7)

    total_products = Column(Integer, default=0)
    total_orders = Column(Integer, default=0)
    rating = Column(Numeric(3, 2), default=0.00)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    users = relationship("User", back_populates="merchant", foreign_keys="User.merchant_id")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    products = relationship("Product", back_populates="merchant")
    warehouses = relationship("Warehouse", back_populates="merchant")
    addresses = relationship("MerchantAddress", back_populates="merchant", cascade="all, delete-orphan")
    bank_accounts = relationship("MerchantBankAccount", back_populates="merchant", cascade="all, delete-orphan")
    documents = relationship("MerchantDocument", back_populates="merchant", cascade="all, delete-orphan")

    @property
    def can_trade(self) -> bool:
        return self.status == MerchantStatus.APPROVED.value and self.deleted_at is None

    @property
    def status_enum(self) -> MerchantStatus:
        try:
            return MerchantStatus(self.status)
        except ValueError:
            return MerchantStatus.PENDING

    @property
    def status_label(self) -> str:
        return self.status_enum.label


class MerchantAddress(Base):
    __tablename__ = "merchant_addresses"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), default="registered")  # registered, billing, warehouse
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(100), default="India")
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="addresses")


class MerchantBankAccount(Base):
    __tablename__ = "merchant_bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    account_holder_name = Column(String(255), nullable=False)
    account_number = Column(String(50), nullable=False)
    ifsc_code = Column(String(20), nullable=False)
    bank_name = Column(String(100), nullable=False)
    branch_name = Column(String(100), nullable=True)
    is_verified = Column(Boolean, default=False)
    is_primary = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="bank_accounts")


class MerchantDocument(Base):
    __tablename__ = "merchant_documents"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String(50), nullable=False)  # pan, gst, cancelled_cheque, etc.
    file_path = Column(String(255), nullable=False)
    status = Column(String(50), default="pending")  # pending, verified, rejected
    rejection_reason = Column(Text, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="documents")
