from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    auditable_type = Column(String(100), nullable=True)
    auditable_id = Column(Integer, nullable=True)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])


class CommissionRule(Base):
    __tablename__ = "commission_rules"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    rate = Column(Numeric(5, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant")
    category = relationship("Category")


class Payout(Base):
    __tablename__ = "payouts"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    payout_number = Column(String(50), unique=True, nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    gross_sales = Column(Numeric(14, 2), default=0.00)
    commission_total = Column(Numeric(14, 2), default=0.00)
    tax_total = Column(Numeric(14, 2), default=0.00)
    net_payout = Column(Numeric(14, 2), default=0.00)

    status = Column(String(50), default="pending")  # pending, approved, processing, paid, failed
    processed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    processed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant")
    processor = relationship("User", foreign_keys=[processed_by])


class BulkImportJob(Base):
    __tablename__ = "bulk_import_jobs"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(255), nullable=False)
    status = Column(String(50), default="queued")
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    successful_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    errors = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    merchant = relationship("Merchant")
