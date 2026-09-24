from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.taxonomy import Category, Brand, Attribute, AttributeValue
from app.models.user import User

router = APIRouter(tags=["taxonomy"])

@router.get("/taxonomy/categories")
def get_categories(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    categories = db.query(Category).filter(Category.deleted_at.is_(None), Category.is_active == True).order_by(Category.sort_order).all()
    
    # Return as list of categories with parent/path metadata
    result = []
    for cat in categories:
        result.append({
            "id": cat.id,
            "parent_id": cat.parent_id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "path": cat.path,
            "level": cat.level,
            "is_leaf": bool(cat.is_leaf),
            "commission_rate": float(cat.commission_rate) if cat.commission_rate else None,
            "tax_rate": float(cat.tax_rate) if cat.tax_rate else None,
            "image_url": f"/storage/{cat.image_path}" if cat.image_path else None,
            "icon": cat.icon,
        })
    return result

@router.get("/taxonomy/categories/{category_id}/attributes")
def get_category_attributes(category_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cat = db.query(Category).filter(Category.id == category_id, Category.deleted_at.is_(None)).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")

    attrs = []
    for attr in cat.attributes:
        attrs.append({
            "id": attr.id,
            "name": attr.name,
            "code": attr.code,
            "type": attr.type,
            "is_required": bool(attr.is_required),
            "is_filterable": bool(attr.is_filterable),
            "is_variant_axis": bool(attr.is_variant_axis),
            "values": [
                {
                    "id": val.id,
                    "value": val.value,
                    "label": val.label,
                    "hex_color": val.hex_color,
                }
                for val in attr.values
            ]
        })
    return attrs

@router.get("/taxonomy/brands")
def get_brands(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    brands = db.query(Brand).filter(Brand.deleted_at.is_(None), Brand.status == "approved").order_by(Brand.name).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "slug": b.slug,
            "logo_url": f"/storage/{b.logo_path}" if b.logo_path else None,
            "description": b.description,
            "website": b.website,
        }
        for b in brands
    ]

@router.get("/attributes")
def get_all_attributes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    attributes = db.query(Attribute).order_by(Attribute.sort_order).all()
    return [
        {
            "id": attr.id,
            "name": attr.name,
            "code": attr.code,
            "type": attr.type,
            "is_required": bool(attr.is_required),
            "is_filterable": bool(attr.is_filterable),
            "is_variant_axis": bool(attr.is_variant_axis),
        }
        for attr in attributes
    ]

@router.get("/attributes/{attribute_id}/values")
def get_attribute_values(attribute_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    vals = db.query(AttributeValue).filter(AttributeValue.attribute_id == attribute_id).order_by(AttributeValue.sort_order).all()
    return [
        {
            "id": v.id,
            "value": v.value,
            "label": v.label,
            "hex_color": v.hex_color,
        }
        for v in vals
    ]
