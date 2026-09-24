import os
import time
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.models.user import User
from app.models.ai_model import AiModel, ProductTryOn
from app.core.permissions import Permissions

router = APIRouter(prefix="/admin", tags=["admin-ai-models"])

class AiModelCreateSchema(BaseModel):
    name: str
    gender: Optional[str] = "unisex"
    body_type: Optional[str] = None
    height_cm: Optional[str] = None
    reference_size: Optional[str] = None
    description: Optional[str] = None
    supported_categories: Optional[List[str]] = None
    sort_order: Optional[int] = 0

def format_ai_model(m: AiModel) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "slug": m.slug,
        "description": m.description,
        "gender": m.gender,
        "body_type": m.body_type,
        "height_cm": m.height_cm,
        "reference_size": m.reference_size,
        "pose_image_url": f"/storage/{m.pose_image_path}" if m.pose_image_path else None,
        "thumb_url": f"/storage/{m.thumb_path}" if m.thumb_path else None,
        "supported_categories": m.supported_categories or [],
        "is_active": bool(m.is_active),
        "sort_order": m.sort_order,
    }

@router.get("/ai-models")
def list_admin_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.AI_MODEL_VIEW))
):
    models = db.query(AiModel).order_by(AiModel.sort_order).all()
    return {"data": [format_ai_model(m) for m in models]}

@router.post("/ai-models")
def create_model(
    data: AiModelCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.AI_MODEL_MANAGE))
):
    slug = data.name.lower().replace(" ", "-")
    m = AiModel(
        name=data.name,
        slug=slug,
        gender=data.gender or "unisex",
        body_type=data.body_type,
        height_cm=data.height_cm,
        reference_size=data.reference_size,
        description=data.description,
        supported_categories=data.supported_categories,
        sort_order=data.sort_order or 0,
        is_active=True,
        created_by=current_user.id
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"data": format_ai_model(m)}

@router.put("/ai-models/{model_id}")
def update_model(
    model_id: int,
    data: AiModelCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.AI_MODEL_MANAGE))
):
    m = db.query(AiModel).filter(AiModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="AI Model not found.")

    for k, v in data.model_dump().items():
        setattr(m, k, v)

    db.commit()
    db.refresh(m)
    return {"data": format_ai_model(m)}

@router.delete("/ai-models/{model_id}")
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.AI_MODEL_MANAGE))
):
    m = db.query(AiModel).filter(AiModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="AI Model not found.")

    db.delete(m)
    db.commit()
    return {"message": "AI Model deleted."}

@router.post("/ai-models/{model_id}/pose")
async def upload_pose(
    model_id: int,
    pose: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.AI_MODEL_MANAGE))
):
    m = db.query(AiModel).filter(AiModel.id == model_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="AI Model not found.")

    dest_dir = settings.STORAGE_DIR / "ai-models"
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{m.slug}_{int(time.time())}.jpg"
    dest_path = dest_dir / filename

    content = await pose.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    m.pose_image_path = f"ai-models/{filename}"
    m.thumb_path = f"ai-models/{filename}"
    db.commit()
    db.refresh(m)

    return {"data": format_ai_model(m)}

@router.post("/try-ons/{try_on_id}/publish")
def publish_try_on(
    try_on_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.TRY_ON_PUBLISH))
):
    try_on = db.query(ProductTryOn).filter(ProductTryOn.id == try_on_id).first()
    if not try_on:
        raise HTTPException(status_code=404, detail="Try-on not found.")

    if try_on.is_placeholder:
        raise HTTPException(
            status_code=422,
            detail="Placeholder renders (imagined by text-to-image models) cannot be published live to shoppers."
        )

    try_on.is_published = True
    try_on.published_at = datetime.utcnow()
    try_on.published_by = current_user.id
    db.commit()
    return {"message": "Try-on look published to catalog."}
