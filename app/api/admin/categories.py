from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.models.user import User
from app.models.taxonomy import Category
from app.core.permissions import Permissions

router = APIRouter(prefix="/admin/categories", tags=["admin-categories"])

class CategorySchema(BaseModel):
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    commission_rate: Optional[float] = None
    tax_rate: Optional[float] = None
    hsn_code: Optional[str] = None
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0

def format_cat(c: Category) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "slug": c.slug,
        "parent_id": c.parent_id,
        "path": c.path,
        "level": c.level,
        "is_leaf": bool(c.is_leaf),
        "commission_rate": float(c.commission_rate) if c.commission_rate else None,
        "tax_rate": float(c.tax_rate) if c.tax_rate else None,
        "hsn_code": c.hsn_code,
        "is_active": bool(c.is_active),
        "sort_order": c.sort_order,
    }

@router.get("")
def list_admin_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.CATEGORY_MANAGE))
):
    categories = db.query(Category).filter(Category.deleted_at.is_(None)).order_by(Category.sort_order).all()
    return {"data": [format_cat(c) for c in categories]}

@router.post("")
def create_category(
    data: CategorySchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.CATEGORY_MANAGE))
):
    slug = data.name.lower().replace(" ", "-")
    cat = Category(
        name=data.name,
        slug=slug,
        parent_id=data.parent_id,
        description=data.description,
        commission_rate=data.commission_rate,
        tax_rate=data.tax_rate,
        hsn_code=data.hsn_code,
        is_active=data.is_active if data.is_active is not None else True,
        sort_order=data.sort_order or 0
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"data": format_cat(cat)}

@router.put("/{category_id}")
def update_category(
    category_id: int,
    data: CategorySchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.CATEGORY_MANAGE))
):
    cat = db.query(Category).filter(Category.id == category_id, Category.deleted_at.is_(None)).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")

    for k, v in data.model_dump().items():
        setattr(cat, k, v)

    db.commit()
    db.refresh(cat)
    return {"data": format_cat(cat)}

@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.CATEGORY_MANAGE))
):
    cat = db.query(Category).filter(Category.id == category_id, Category.deleted_at.is_(None)).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")

    db.delete(cat)
    db.commit()
    return {"message": "Category deleted."}
