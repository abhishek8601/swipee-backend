import logging
import re
from datetime import datetime, timedelta
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db, SessionLocal
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.product import Product, ProductImage
from app.models.ai_model import IMPORTED_FROM_DRIVE, AiModel, ProductTryOn
from app.services import drive_storage, reel_service, video_provider
from app.services.tryon_service import TryOnService

logger = logging.getLogger("swipee.reels")

router = APIRouter(prefix="/merchant", tags=["merchant-try-ons"])

class CreateTryOnSchema(BaseModel):
    ai_model_id: int
    colour_attribute_value_id: Optional[int] = None
    source_image_id: Optional[int] = None

class ReelGenerationSchema(CreateTryOnSchema):
    scene_style: Literal["studio", "street", "runway", "festive"] = "studio"
    duration_seconds: int = 20

def format_try_on(to: ProductTryOn) -> dict:
    data = {
        "id": to.id,
        "product_id": to.product_id,
        "ai_model_id": to.ai_model_id,
        "model_name": to.ai_model.name if to.ai_model else None,
        "model_gender": to.ai_model.gender if to.ai_model else None,
        "colour_attribute_value_id": to.colour_attribute_value_id,
        "colour_name": to.colour_value.label if to.colour_value else None,
        "status": to.status,
        "result_url": f"/storage/{to.result_path}" if to.result_path else None,
        "thumb_url": f"/storage/{to.thumb_path}" if to.thumb_path else None,
        "provider": to.provider,
        "is_placeholder": bool(to.is_placeholder),
        "is_published": bool(to.is_published),
        "error_message": to.error_message,
        "latency_ms": to.latency_ms,
        "created_at": to.created_at.isoformat() if to.created_at else None,
        "media_type": to.media_type or "image",
    }
    if data["media_type"] == "video":
        blockers = reel_service.publish_blockers(to)
        data.update({
            "product": {
                "id": to.product.id,
                "name": to.product.name,
                "status": to.product.status,
                "image_url": f"/storage/{to.product.primary_image.image_path}" if to.product.primary_image else None,
            } if to.product else None,
            "source_image_id": to.source_image_id,
            "source_image_url": f"/storage/{to.source_image.image_path}" if to.source_image else None,
            "scene_style": to.scene_style,
            "duration_seconds": to.duration_seconds,
            "generation_attempts": to.generation_attempts or 0,
            "video_provider": to.video_provider,
            "video_url": reel_service.signed_video_url(to),
            "poster_url": reel_service.poster_url(to),
            "source": "drive" if to.video_provider == IMPORTED_FROM_DRIVE else "ai",
            "storage_status": to.storage_status,
            "storage_provider": to.storage_provider,
            "storage_file_id": to.storage_file_id,
            "storage_error": to.storage_error,
            "stored_at": to.stored_at.isoformat() if to.stored_at else None,
            "published_at": to.published_at.isoformat() if to.published_at else None,
            "moderation_status": to.moderation_status,
            "can_publish": not blockers,
            "publish_blockers": blockers,
            "updated_at": to.updated_at.isoformat() if to.updated_at else None,
        })
    return data

async def run_try_on_background(try_on_id: int):
    db = SessionLocal()
    try:
        await TryOnService.process_try_on(db, try_on_id)
    finally:
        db.close()

def owned_reel(db: Session, user: User, reel_id: int) -> ProductTryOn:
    reel = db.query(ProductTryOn).filter(
        ProductTryOn.id == reel_id,
        ProductTryOn.merchant_id == user.merchant_id,
    ).first() if user.merchant_id else None
    if not reel:
        # Same answer for "absent" and "someone else's": no existence oracle.
        raise HTTPException(status_code=404, detail="Reel not found.")
    return reel

def lease_held(reel: ProductTryOn) -> bool:
    return bool(reel.lease_until and reel.lease_until > datetime.utcnow())

@router.get("/ai-models")
def list_available_models(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    models = db.query(AiModel).filter(AiModel.is_active == True).order_by(AiModel.sort_order, AiModel.id).all()
    return {
        "data": [
            {
                "id": m.id,
                "persona_id": m.slug,
                "name": m.name,
                "slug": m.slug,
                "description": m.description,
                "gender": m.gender,
                "body_type": m.body_type,
                "height_cm": m.height_cm,
                "reference_size": m.reference_size,
                "pose_image_url": f"/storage/{m.pose_image_path}" if m.pose_image_path else None,
                "thumb_url": f"/storage/{m.thumb_path}" if m.thumb_path else (f"/storage/{m.pose_image_path}" if m.pose_image_path else None),
                "supported_categories": m.supported_categories or [],
                "is_available": bool(m.is_active),
            }
            for m in models
        ]
    }

@router.get("/products/{product_id}/try-ons")
def list_product_try_ons(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == current_user.merchant_id,
        Product.deleted_at.is_(None)
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    try_ons = db.query(ProductTryOn).filter(
        ProductTryOn.product_id == product.id
    ).order_by(ProductTryOn.created_at.desc()).all()

    return {"data": [format_try_on(to) for to in try_ons]}

@router.post("/products/{product_id}/try-ons")
def create_try_on(
    product_id: int,
    data: CreateTryOnSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == current_user.merchant_id,
        Product.deleted_at.is_(None)
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    model = db.query(AiModel).filter(AiModel.id == data.ai_model_id, AiModel.is_active == True).first()
    if not model:
        raise HTTPException(status_code=404, detail="AI Model not found.")

    # Find garment image
    source_img_id = data.source_image_id
    if not source_img_id:
        img = product.primary_image
        source_img_id = img.id if img else None

    try_on = ProductTryOn(
        product_id=product.id,
        ai_model_id=model.id,
        colour_attribute_value_id=data.colour_attribute_value_id,
        merchant_id=current_user.merchant_id,
        source_image_id=source_img_id,
        status="queued"
    )
    db.add(try_on)
    db.commit()
    db.refresh(try_on)

    # Queue execution
    background_tasks.add_task(run_try_on_background, try_on.id)

    return {"data": format_try_on(try_on)}


@router.get("/reels/capabilities")
def reel_capabilities(current_user: User = Depends(get_current_user)):
    """Which parts of the reel pipeline are configured. Names env vars, never values."""
    return {
        "data": {
            "video_generation": {"configured": video_provider.is_configured(), "provider": settings.VIDEO_PROVIDER or None, "missing": video_provider.missing_configuration()},
            "google_drive": {"configured": drive_storage.is_configured(), "missing": drive_storage.missing_configuration()},
            "keyframe_driver": settings.TRYON_DRIVER,
            "keyframe_is_placeholder": True,
            "placeholder_publish_allowed": settings.TRYON_ALLOW_PLACEHOLDER_PUBLISH,
            "scene_styles": list(reel_service.SCENE_PROMPTS),
            "duration_seconds": {"min": 20, "max": 25},
        }
    }


@router.get("/reels")
def list_reels(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    media_type: Optional[Literal["image", "video"]] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List AI creative assets available for preview/publishing as reels."""
    q = db.query(ProductTryOn).filter(
        ProductTryOn.merchant_id == current_user.merchant_id,
    )
    if media_type:
        q = q.filter(ProductTryOn.media_type == media_type)
    if status:
        q = q.filter(ProductTryOn.status == status)
    total = q.count()
    rows = q.order_by(ProductTryOn.created_at.desc(), ProductTryOn.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "data": [format_try_on(row) for row in rows],
        "meta": {"page": page, "per_page": per_page, "total": total, "has_more": page * per_page < total},
    }


@router.get("/reels/{try_on_id}")
def get_reel(try_on_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Status poll / preview for one reel."""
    return {"data": format_try_on(owned_reel(db, current_user, try_on_id))}


IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,64}$")

@router.post("/products/{product_id}/reels")
def generate_reel(
    product_id: int,
    data: ReelGenerationSchema,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade),
):
    """Queue an AI video reel: selected AI model wearing this product.

    Returns 202 with the reel immediately; poll GET /merchant/reels/{id}.
    Repeating a request with the same Idempotency-Key, or while an identical
    reel is still generating, returns the existing reel instead of a new one.
    """
    if data.duration_seconds < 20 or data.duration_seconds > 25:
        raise HTTPException(status_code=422, detail="Reel duration must be between 20 and 25 seconds.")
    if idempotency_key is not None and not IDEMPOTENCY_KEY.match(idempotency_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be 8-64 characters of letters, digits, '-', '_', ':' or '.'.")
    if not current_user.merchant_id:
        raise HTTPException(status_code=403, detail="Only merchant accounts can generate reels.")
    merchant_id = current_user.merchant_id

    if idempotency_key:
        existing = db.query(ProductTryOn).filter(ProductTryOn.merchant_id == merchant_id, ProductTryOn.idempotency_key == idempotency_key).first()
        if existing:
            return {"message": "Reel already requested.", "deduplicated": True, "data": format_try_on(existing)}

    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == merchant_id,
        Product.deleted_at.is_(None),
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    model = db.query(AiModel).filter(AiModel.id == data.ai_model_id, AiModel.is_active == True).first()
    if not model:
        raise HTTPException(status_code=422, detail="Selected AI model is unavailable.")

    if data.source_image_id:
        image = db.query(ProductImage).filter(ProductImage.id == data.source_image_id, ProductImage.product_id == product.id).first()
        if not image:
            raise HTTPException(status_code=422, detail="The selected image does not belong to this product.")
    else:
        image = product.primary_image
    if not image or not (settings.STORAGE_DIR / image.image_path).is_file():
        raise HTTPException(status_code=422, detail="This product has no usable image. Upload a product image first.")

    if not video_provider.is_configured():
        raise HTTPException(status_code=503, detail={
            "message": "AI video generation is not configured on this server.",
            "missing_configuration": video_provider.missing_configuration(),
        })

    duplicate = db.query(ProductTryOn).filter(
        ProductTryOn.merchant_id == merchant_id,
        ProductTryOn.product_id == product.id,
        ProductTryOn.ai_model_id == model.id,
        ProductTryOn.source_image_id == image.id,
        ProductTryOn.scene_style == data.scene_style,
        ProductTryOn.media_type == "video",
        ProductTryOn.status.in_(reel_service.ACTIVE_STATUSES),
    ).first()
    if duplicate:
        return {"message": "An identical reel is already generating.", "deduplicated": True, "data": format_try_on(duplicate)}

    active = db.query(ProductTryOn).filter(
        ProductTryOn.merchant_id == merchant_id, ProductTryOn.media_type == "video",
        ProductTryOn.status.in_(reel_service.ACTIVE_STATUSES),
    ).count()
    if active >= settings.REEL_MAX_ACTIVE_PER_MERCHANT:
        raise HTTPException(status_code=429, detail=f"You already have {active} reels generating. Wait for one to finish.")
    today = db.query(ProductTryOn).filter(
        ProductTryOn.merchant_id == merchant_id, ProductTryOn.media_type == "video",
        ProductTryOn.created_at >= datetime.utcnow() - timedelta(days=1),
    ).count()
    if today >= settings.REEL_DAILY_LIMIT_PER_MERCHANT:
        raise HTTPException(status_code=429, detail=f"Daily reel limit reached ({settings.REEL_DAILY_LIMIT_PER_MERCHANT} per 24 hours).")

    try_on = ProductTryOn(
        product_id=product.id,
        ai_model_id=model.id,
        colour_attribute_value_id=data.colour_attribute_value_id,
        merchant_id=merchant_id,
        source_image_id=image.id,
        status="queued",
        media_type="video",
        scene_style=data.scene_style,
        duration_seconds=data.duration_seconds,
        idempotency_key=idempotency_key,
        storage_status="pending",
    )
    db.add(try_on)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent request with the same Idempotency-Key won the insert.
        db.rollback()
        existing = db.query(ProductTryOn).filter(ProductTryOn.merchant_id == merchant_id, ProductTryOn.idempotency_key == idempotency_key).first()
        if not existing:
            raise
        return {"message": "Reel already requested.", "deduplicated": True, "data": format_try_on(existing)}
    db.refresh(try_on)
    background_tasks.add_task(reel_service.process_reel, try_on.id)
    return JSONResponse(status_code=202, content={"message": "Reel generation queued.", "deduplicated": False, "data": format_try_on(try_on)})


@router.post("/reels/{try_on_id}/publish")
def publish_reel(
    try_on_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade),
):
    try_on = owned_reel(db, current_user, try_on_id)
    if try_on.is_published:
        return {"message": "Reel is already published.", "data": format_try_on(try_on)}
    blockers = reel_service.publish_blockers(try_on)
    if blockers:
        raise HTTPException(status_code=422, detail={"message": blockers[0], "errors": {"publish": blockers}})
    try_on.is_published = True
    try_on.published_at = datetime.utcnow()
    try_on.published_by = current_user.id
    db.commit()
    db.refresh(try_on)
    return {"message": "Reel published with its product tag.", "data": format_try_on(try_on)}


@router.post("/reels/{try_on_id}/unpublish")
def unpublish_reel(
    try_on_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade),
):
    try_on = owned_reel(db, current_user, try_on_id)
    try_on.is_published = False
    db.commit()
    db.refresh(try_on)
    return {"message": "Reel removed from the buyer feed.", "data": format_try_on(try_on)}


@router.post("/reels/{try_on_id}/retry")
def retry_reel(
    try_on_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade),
):
    return retry_try_on(try_on_id, background_tasks, db, current_user)


@router.post("/reels/{try_on_id}/retry-upload")
def retry_reel_upload(
    try_on_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade),
):
    reel = owned_reel(db, current_user, try_on_id)
    if reel.media_type != "video" or reel.status != "completed":
        raise HTTPException(status_code=422, detail="Only a completed video reel can be uploaded.")
    if reel.storage_status == "uploaded":
        return {"message": "Reel is already stored on Google Drive.", "data": format_try_on(reel)}
    if reel.storage_status == "uploading" and lease_held(reel):
        raise HTTPException(status_code=409, detail="An upload is already in progress.")
    if not drive_storage.is_configured():
        raise HTTPException(status_code=503, detail={
            "message": "Google Drive storage is not configured on this server.",
            "missing_configuration": drive_storage.missing_configuration(),
        })
    reel.storage_status = "pending"
    reel.storage_error = None
    db.commit()
    background_tasks.add_task(reel_service.upload_reel, reel.id)
    db.refresh(reel)
    return {"message": "Upload to Google Drive queued.", "data": format_try_on(reel)}


@router.post("/try-ons/{try_on_id}/retry")
def retry_try_on(
    try_on_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    try_on = db.query(ProductTryOn).filter(
        ProductTryOn.id == try_on_id,
        ProductTryOn.merchant_id == current_user.merchant_id
    ).first()
    if not try_on:
        raise HTTPException(status_code=404, detail="Try-on not found.")
    # Retrying a running job would start a second render of the same row.
    if try_on.status != "failed":
        raise HTTPException(status_code=409, detail=f"Only failed generations can be retried (current status: {try_on.status}).")

    if try_on.media_type == "video":
        if not video_provider.is_configured():
            raise HTTPException(status_code=503, detail={
                "message": "AI video generation is not configured on this server.",
                "missing_configuration": video_provider.missing_configuration(),
            })
        # Keeps the keyframe and provider job id, so the retry resumes rather than repays.
        try_on.status = "queued"
        try_on.error_message = None
        db.commit()
        background_tasks.add_task(reel_service.process_reel, try_on.id)
    else:
        try_on.status = "queued"
        try_on.error_message = None
        db.commit()
        background_tasks.add_task(run_try_on_background, try_on.id)
    db.refresh(try_on)
    return {"data": format_try_on(try_on)}

@router.delete("/try-ons/{try_on_id}")
async def delete_try_on(
    try_on_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    try_on = db.query(ProductTryOn).filter(
        ProductTryOn.id == try_on_id,
        ProductTryOn.merchant_id == current_user.merchant_id
    ).first()
    if not try_on:
        raise HTTPException(status_code=404, detail="Try-on not found.")
    if lease_held(try_on):
        raise HTTPException(status_code=409, detail="This reel is still being processed. Try again once it finishes.")

    video = reel_service.video_file(try_on)
    # An imported reel only points at the super admin's original in Drive: never delete that.
    drive_file_id = None if try_on.video_provider == IMPORTED_FROM_DRIVE else try_on.storage_file_id
    db.delete(try_on)
    db.commit()

    if video:
        video.unlink(missing_ok=True)
    if drive_file_id and drive_storage.is_configured():
        try:
            await drive_storage.delete_file(drive_file_id)
        except drive_storage.DriveError as e:
            logger.warning("Reel %s deleted but its Drive file %s was not: %s", try_on_id, drive_file_id, e)
            return {"message": "Try-on deleted. The Google Drive copy could not be removed and may need manual cleanup."}
    return {"message": "Try-on deleted successfully."}
