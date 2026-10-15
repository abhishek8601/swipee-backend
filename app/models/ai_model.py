from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Numeric, UniqueConstraint
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


IMPORTED_FROM_DRIVE = "drive_import"


class ProductTryOn(Base):
    __tablename__ = "product_try_ons"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    # Empty for reels imported from Google Drive (no AI persona involved).
    ai_model_id = Column(Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=True, index=True)
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

    # Reel (video) fields. An image try-on leaves these empty; a reel uses the
    # try-on render above as its keyframe and the video provider animates it.
    media_type = Column(String(20), default="image", nullable=False, server_default="image")  # image, video
    scene_style = Column(String(50), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    video_path = Column(String(255), nullable=True)  # relative to PRIVATE_STORAGE_DIR
    video_provider = Column(String(50), nullable=True)  # "replicate" for generated, IMPORTED_FROM_DRIVE for imports
    video_job_id = Column(String(255), nullable=True)
    generation_attempts = Column(Integer, default=0, nullable=False, server_default="0")
    lease_until = Column(DateTime, nullable=True)  # worker claim, prevents two workers on one reel
    idempotency_key = Column(String(64), nullable=True)

    # Upload status is tracked apart from generation so a finished video whose
    # Drive upload failed can be re-uploaded without re-rendering.
    storage_status = Column(String(30), nullable=True)  # pending, uploading, uploaded, failed, not_configured
    storage_provider = Column(String(30), nullable=True)
    storage_file_id = Column(String(255), nullable=True)
    storage_error = Column(Text, nullable=True)
    storage_attempts = Column(Integer, default=0, nullable=False, server_default="0")
    stored_at = Column(DateTime, nullable=True)

    moderation_status = Column(String(30), nullable=True)  # approved, rejected, disabled (set by super admin)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_try_on_merchant_idempotency"),
    )

    product = relationship("Product", back_populates="try_ons")
    ai_model = relationship("AiModel", back_populates="try_ons")
    colour_value = relationship("AttributeValue", foreign_keys=[colour_attribute_value_id])
    merchant = relationship("Merchant")
    source_image = relationship("ProductImage", foreign_keys=[source_image_id])
    publisher = relationship("User", foreign_keys=[published_by])
