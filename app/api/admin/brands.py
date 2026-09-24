import os
import time
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.models.user import User
from app.models.taxonomy import Brand
from app.core.permissions import Permissions

router = APIRouter(prefix="/admin/brands", tags=["admin-brands"])

class BrandSchema(BaseModel):
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    is_active: Optional[bool] = True

def format_brand(b: Brand) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "slug": b.slug,
        "logo_url": f"/storage/{b.logo_path}" if b.logo_path else None,
        "description": b.description,
        "website": b.website,
        "is_active": bool(b.is_active),
        "status": b.status,
    }

@router.get("")
def list_admin_brands(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.BRAND_VIEW))
):
    brands = db.query(Brand).filter(Brand.deleted_at.is_(None)).order_by(Brand.name).all()
    return {"data": [format_brand(b) for b in brands]}

@router.post("")
def create_brand(
    data: BrandSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.BRAND_MANAGE))
):
    slug = data.name.lower().replace(" ", "-")
    b = Brand(
        name=data.name,
        slug=slug,
        description=data.description,
        website=data.website,
        is_active=data.is_active if data.is_active is not None else True,
        status="approved",
        created_by=current_user.id
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"data": format_brand(b)}

@router.put("/{brand_id}")
def update_brand(
    brand_id: int,
    data: BrandSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.BRAND_MANAGE))
):
    b = db.query(Brand).filter(Brand.id == brand_id, Brand.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found.")

    for k, v in data.model_dump().items():
        setattr(b, k, v)

    db.commit()
    db.refresh(b)
    return {"data": format_brand(b)}

@router.delete("/{brand_id}")
def delete_brand(
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.BRAND_MANAGE))
):
    b = db.query(Brand).filter(Brand.id == brand_id, Brand.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found.")

    db.delete(b)
    db.commit()
    return {"message": "Brand deleted."}

@router.post("/{brand_id}/approve")
def approve_brand(
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.BRAND_APPROVE))
):
    b = db.query(Brand).filter(Brand.id == brand_id, Brand.deleted_at.is_(None)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found.")

    b.status = "approved"
    db.commit()
    db.refresh(b)
    return {"data": format_brand(b)}
