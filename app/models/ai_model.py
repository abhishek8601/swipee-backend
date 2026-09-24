from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Numeric
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class AiModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)

    gender = Column(String(20), default="unisex")  # male, female, unisex
    body_type = Column(String(50), nullable=True)
    height_cm = Column(String(10), nullable=True)
    reference_size = Column(String(20), nullable=True)

    pose_image_path = Column(String(255), nullable=True)
    thumb_path = Column(String(255), nullable=True)
    mask_path = Column(String(255), nullable=True)

    supported_categories = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    provider_meta = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    try_ons = relationship("ProductTryOn", back_populates="ai_model", cascade="all, delete-orphan")


class ProductTryOn(Base):
    __tablename__ = "product_try_ons"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_model_id = Column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True)
    colour_attribute_value_id = Column(Integer, ForeignKey("attribute_values.id", ondelete="CASCADE"), nullable=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_image_id = Column(Integer, ForeignKey("product_images.id", ondelete="SET NULL"), nullable=True)

    status = Column(String(50), default="queued")  # queued, processing, completed, failed, cancelled
    result_path = Column(String(255), nullable=True)
    thumb_path = Column(String(255), nullable=True)

    provider = Column(String(50), nullable=True)
    is_placeholder = Column(Boolean, default=False)
    provider_job_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)

    latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(8, 4), nullable=True)
    prompt_used = Column(Text, nullable=True)

    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="try_ons")
    ai_model = relationship("AiModel", back_populates="try_ons")
    colour_value = relationship("AttributeValue", foreign_keys=[colour_attribute_value_id])
    merchant = relationship("Merchant")
    source_image = relationship("ProductImage", foreign_keys=[source_image_id])
    publisher = relationship("User", foreign_keys=[published_by])
