import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.product import Product, ProductVariant, ProductImage, ProductAttributeValue, ProductApprovalHistory
from app.models.taxonomy import Category, Brand
from app.core.enums import ProductStatus

router = APIRouter(prefix="/merchant/products", tags=["merchant-products"])

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)

def format_product_list_item(p: Product) -> dict:
    primary = p.primary_image
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "style_code": p.style_code,
        "mrp": float(p.mrp),
        "selling_price": float(p.selling_price),
        "status": p.status,
        "status_label": p.status_label,
        "is_active": bool(p.is_active),
        "category": {"id": p.category.id, "name": p.category.name} if p.category else None,
        "brand": {"id": p.brand.id, "name": p.brand.name} if p.brand else None,
        "primary_image_url": f"/storage/{primary.image_path}" if primary else None,
        "variants_count": len(p.variants),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }

def format_product_detail(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "style_code": p.style_code,
        "short_description": p.short_description,
        "description": p.description,
        "highlights": p.highlights or [],
        "mrp": float(p.mrp),
        "selling_price": float(p.selling_price),
        "cost_price": float(p.cost_price) if p.cost_price else None,
        "hsn_code": p.hsn_code,
        "tax_rate": float(p.tax_rate) if p.tax_rate else None,
        "tax_inclusive": bool(p.tax_inclusive),
        "country_of_origin": p.country_of_origin,
        "manufacturer_name": p.manufacturer_name,
        "manufacturer_address": p.manufacturer_address,
        "packer_name": p.packer_name,
        "packer_address": p.packer_address,
        "importer_name": p.importer_name,
        "importer_address": p.importer_address,
        "wash_care": p.wash_care,
        "model_size_note": p.model_size_note,
        "status": p.status,
        "status_label": p.status_label,
        "rejection_reason": p.rejection_reason,
        "is_active": bool(p.is_active),
        "is_featured": bool(p.is_featured),
        "category": {
            "id": p.category.id,
            "name": p.category.name,
            "path": p.category.path
        } if p.category else None,
        "brand": {
            "id": p.brand.id,
            "name": p.brand.name
        } if p.brand else None,
        "variants": [
            {
                "id": v.id,
                "sku": v.sku,
                "barcode": v.barcode,
                "size": {"id": v.size_value.id, "label": v.size_value.label} if v.size_value else None,
                "colour": {"id": v.colour_value.id, "label": v.colour_value.label, "hex_color": v.colour_value.hex_color} if v.colour_value else None,
                "mrp": float(v.mrp) if v.mrp is not None else float(p.mrp),
                "selling_price": float(v.selling_price) if v.selling_price is not None else float(p.selling_price),
                "is_active": bool(v.is_active),
                "inventory": [
                    {
                        "warehouse_id": inv.warehouse_id,
                        "warehouse_name": inv.warehouse.name,
                        "on_hand": inv.on_hand,
                        "reserved": inv.reserved,
                        "available": inv.on_hand - inv.reserved,
                    }
                    for inv in v.inventory
                ]
            }
            for v in p.variants if v.deleted_at is None
        ],
        "images": [
            {
                "id": img.id,
                "image_url": f"/storage/{img.image_path}",
                "thumb_url": f"/storage/{img.thumb_path}" if img.thumb_path else f"/storage/{img.image_path}",
                "colour_attribute_value_id": img.colour_attribute_value_id,
                "is_primary": bool(img.is_primary),
                "sort_order": img.sort_order,
            }
            for img in sorted(p.images, key=lambda x: x.sort_order)
        ],
        "attributes": [
            {
                "attribute_id": pav.attribute_id,
                "name": pav.attribute.name,
                "attribute_value_id": pav.attribute_value_id,
                "text_value": pav.text_value,
                "label": pav.value.label if pav.value else pav.text_value,
            }
            for pav in p.attribute_values
        ],
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }

class ProductCreateSchema(BaseModel):
    category_id: int
    brand_id: int
    name: str
    style_code: str
    mrp: float
    selling_price: float
    cost_price: Optional[float] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    highlights: Optional[List[str]] = None
    hsn_code: Optional[str] = None
    tax_rate: Optional[float] = None
    country_of_origin: Optional[str] = "India"
    manufacturer_name: Optional[str] = None
    manufacturer_address: Optional[str] = None
    packer_name: Optional[str] = None
    packer_address: Optional[str] = None
    importer_name: Optional[str] = None
    importer_address: Optional[str] = None
    wash_care: Optional[str] = None
    model_size_note: Optional[str] = None
    attributes: Optional[List[Dict[str, Any]]] = None

@router.get("")
def list_merchant_products(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Product).filter(
        Product.merchant_id == current_user.merchant_id,
        Product.deleted_at.is_(None)
    )

    if status_filter:
        query = query.filter(Product.status == status_filter)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if search:
        s = f"%{search}%"
        query = query.filter((Product.name.ilike(s)) | (Product.style_code.ilike(s)))

    products = query.order_by(Product.created_at.desc()).all()
    return {"data": [format_product_list_item(p) for p in products]}

@router.post("")
def create_merchant_product(
    data: ProductCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    # Base slug
    base_slug = slugify(data.name)
    slug = base_slug
    counter = 1
    while db.query(Product).filter(Product.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    product = Product(
        merchant_id=current_user.merchant_id,
        category_id=data.category_id,
        brand_id=data.brand_id,
        name=data.name,
        slug=slug,
        style_code=data.style_code,
        mrp=data.mrp,
        selling_price=data.selling_price,
        cost_price=data.cost_price,
        short_description=data.short_description,
        description=data.description,
        highlights=data.highlights,
        hsn_code=data.hsn_code,
        tax_rate=data.tax_rate,
        country_of_origin=data.country_of_origin or "India",
        manufacturer_name=data.manufacturer_name,
        manufacturer_address=data.manufacturer_address,
        packer_name=data.packer_name,
        packer_address=data.packer_address,
        importer_name=data.importer_name,
        importer_address=data.importer_address,
        wash_care=data.wash_care,
        model_size_note=data.model_size_note,
        status=ProductStatus.DRAFT.value,
        is_active=True
    )
    db.add(product)
    db.flush()

    # Add attributes if provided
    if data.attributes:
        for attr in data.attributes:
            pav = ProductAttributeValue(
                product_id=product.id,
                attribute_id=attr["attribute_id"],
                attribute_value_id=attr.get("attribute_value_id"),
                text_value=attr.get("text_value")
            )
            db.add(pav)

    db.commit()
    db.refresh(product)
    return {"data": format_product_detail(product)}

@router.get("/{product_id}")
def show_merchant_product(
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

    return {"data": format_product_detail(product)}

@router.put("/{product_id}")
def update_merchant_product(
    product_id: int,
    data: ProductCreateSchema,
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

    if not product.status_enum.is_editable_by_merchant:
        raise HTTPException(
            status_code=422,
            detail=f"Products in '{product.status_label}' status cannot be edited. Withdraw it to draft first."
        )

    for field, val in data.model_dump(exclude={"attributes"}).items():
        setattr(product, field, val)

    # Replace attributes
    if data.attributes is not None:
        db.query(ProductAttributeValue).filter(ProductAttributeValue.product_id == product.id).delete()
        for attr in data.attributes:
            pav = ProductAttributeValue(
                product_id=product.id,
                attribute_id=attr["attribute_id"],
                attribute_value_id=attr.get("attribute_value_id"),
                text_value=attr.get("text_value")
            )
            db.add(pav)

    db.commit()
    db.refresh(product)
    return {"data": format_product_detail(product)}

@router.delete("/{product_id}")
def delete_merchant_product(
    product_id: int,
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

    product.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "Product archived successfully."}

@router.post("/{product_id}/submit")
def submit_merchant_product(
    product_id: int,
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

    if product.status_enum != ProductStatus.DRAFT and product.status_enum != ProductStatus.REJECTED:
        raise HTTPException(status_code=422, detail=f"Cannot submit product in '{product.status_label}' status.")

    if not product.variants:
        raise HTTPException(status_code=422, detail="A product must have at least one variant before submitting.")

    product.status = ProductStatus.PENDING_REVIEW.value
    product.submitted_at = datetime.utcnow()
    product.rejection_reason = None

    history = ProductApprovalHistory(
        product_id=product.id,
        from_status=ProductStatus.DRAFT.value,
        to_status=ProductStatus.PENDING_REVIEW.value,
        reason="Submitted for review by merchant",
        action_by=current_user.id
    )
    db.add(history)
    db.commit()
    return {"data": format_product_detail(product)}

@router.post("/{product_id}/withdraw")
def withdraw_merchant_product(
    product_id: int,
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

    if product.status_enum != ProductStatus.PENDING_REVIEW:
        raise HTTPException(status_code=422, detail="Only products pending review can be withdrawn.")

    product.status = ProductStatus.DRAFT.value
    db.commit()
    return {"data": format_product_detail(product)}

@router.post("/{product_id}/toggle-active")
def toggle_active_merchant_product(
    product_id: int,
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

    product.is_active = not product.is_active
    db.commit()
    return {"data": format_product_detail(product)}
