from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.product import Product, ProductImage
from app.models.ai_model import AiModel, ProductTryOn
from app.services.tryon_service import TryOnService

router = APIRouter(prefix="/merchant", tags=["merchant-try-ons"])

class CreateTryOnSchema(BaseModel):
    ai_model_id: int
    colour_attribute_value_id: Optional[int] = None
    source_image_id: Optional[int] = None

def format_try_on(to: ProductTryOn) -> dict:
    return {
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
    }

async def run_try_on_background(try_on_id: int):
    db = SessionLocal()
    try:
        await TryOnService.process_try_on(db, try_on_id)
    finally:
        db.close()

@router.get("/ai-models")
def list_available_models(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    models = db.query(AiModel).filter(AiModel.is_active == True).order_by(AiModel.sort_order).all()
    return {
        "data": [
            {
                "id": m.id,
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

    try_on.status = "queued"
    try_on.error_message = None
    db.commit()

    background_tasks.add_task(run_try_on_background, try_on.id)
    return {"data": format_try_on(try_on)}

@router.delete("/try-ons/{try_on_id}")
def delete_try_on(
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

    db.delete(try_on)
    db.commit()
    return {"message": "Try-on deleted successfully."}
