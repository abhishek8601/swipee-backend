from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.product import Product, ProductVariant
from app.models.taxonomy import AttributeValue
from app.models.inventory import Warehouse
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/merchant", tags=["merchant-variants"])

class VariantCreateSchema(BaseModel):
    sku: str
    barcode: Optional[str] = None
    size_attribute_value_id: Optional[int] = None
    colour_attribute_value_id: Optional[int] = None
    mrp: Optional[float] = None
    selling_price: Optional[float] = None
    cost_price: Optional[float] = None
    initial_stock: Optional[int] = 0
    warehouse_id: Optional[int] = None

class MatrixGenerateSchema(BaseModel):
    size_ids: List[int]
    colour_ids: List[int]
    default_price: Optional[float] = None
    default_mrp: Optional[float] = None
    warehouse_id: Optional[int] = None
    initial_stock_per_variant: Optional[int] = 0

def format_variant(v: ProductVariant) -> dict:
    return {
        "id": v.id,
        "product_id": v.product_id,
        "sku": v.sku,
        "barcode": v.barcode,
        "size": {"id": v.size_value.id, "label": v.size_value.label} if v.size_value else None,
        "colour": {"id": v.colour_value.id, "label": v.colour_value.label, "hex_color": v.colour_value.hex_color} if v.colour_value else None,
        "mrp": float(v.effective_mrp),
        "selling_price": float(v.effective_selling_price),
        "cost_price": float(v.cost_price) if v.cost_price else None,
        "is_active": bool(v.is_active),
        "inventory": [
            {
                "id": inv.id,
                "warehouse_id": inv.warehouse_id,
                "warehouse_name": inv.warehouse.name,
                "on_hand": inv.on_hand,
                "reserved": inv.reserved,
                "available": inv.on_hand - inv.reserved,
            }
            for inv in v.inventory
        ]
    }

@router.get("/products/{product_id}/variants")
def list_variants(
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

    variants = [v for v in product.variants if v.deleted_at is None]
    return {"data": [format_variant(v) for v in variants]}

@router.post("/products/{product_id}/variants")
def create_variant(
    product_id: int,
    data: VariantCreateSchema,
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

    # Check unique sku
    if db.query(ProductVariant).filter(ProductVariant.sku == data.sku).first():
        raise HTTPException(status_code=422, detail="A variant with this SKU already exists.")

    variant = ProductVariant(
        product_id=product.id,
        sku=data.sku,
        barcode=data.barcode,
        size_attribute_value_id=data.size_attribute_value_id,
        colour_attribute_value_id=data.colour_attribute_value_id,
        mrp=data.mrp,
        selling_price=data.selling_price,
        cost_price=data.cost_price,
        is_active=True
    )
    db.add(variant)
    db.flush()

    # Initialise stock in warehouse if given or default warehouse
    warehouse = None
    if data.warehouse_id:
        warehouse = db.query(Warehouse).filter(Warehouse.id == data.warehouse_id, Warehouse.merchant_id == current_user.merchant_id).first()
    else:
        warehouse = db.query(Warehouse).filter(Warehouse.merchant_id == current_user.merchant_id, Warehouse.is_primary == True).first()

    if warehouse:
        InventoryService.initialise(
            db=db,
            variant=variant,
            warehouse=warehouse,
            quantity=data.initial_stock or 0,
            actor=current_user
        )

    db.commit()
    db.refresh(variant)
    return {"data": format_variant(variant)}

@router.post("/products/{product_id}/variants/matrix")
def generate_matrix(
    product_id: int,
    data: MatrixGenerateSchema,
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

    warehouse = None
    if data.warehouse_id:
        warehouse = db.query(Warehouse).filter(Warehouse.id == data.warehouse_id, Warehouse.merchant_id == current_user.merchant_id).first()
    else:
        warehouse = db.query(Warehouse).filter(Warehouse.merchant_id == current_user.merchant_id, Warehouse.is_primary == True).first()

    created_variants = []
    for s_id in data.size_ids:
        for c_id in data.colour_ids:
            size = db.query(AttributeValue).filter(AttributeValue.id == s_id).first()
            colour = db.query(AttributeValue).filter(AttributeValue.id == c_id).first()

            sku = f"{product.style_code}-{colour.value[:3].upper() if colour else 'CLR'}-{size.value.upper() if size else 'SZ'}"
            
            # Check if exists
            existing = db.query(ProductVariant).filter(ProductVariant.sku == sku).first()
            if existing:
                continue

            variant = ProductVariant(
                product_id=product.id,
                sku=sku,
                size_attribute_value_id=s_id,
                colour_attribute_value_id=c_id,
                mrp=data.default_mrp or product.mrp,
                selling_price=data.default_price or product.selling_price,
                is_active=True
            )
            db.add(variant)
            db.flush()

            if warehouse:
                InventoryService.initialise(
                    db=db,
                    variant=variant,
                    warehouse=warehouse,
                    quantity=data.initial_stock_per_variant or 0,
                    actor=current_user
                )

            created_variants.append(variant)

    db.commit()
    return {"data": [format_variant(v) for v in created_variants]}

@router.put("/variants/{variant_id}")
def update_variant(
    variant_id: int,
    data: VariantCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    variant = db.query(ProductVariant).join(Product).filter(
        ProductVariant.id == variant_id,
        Product.merchant_id == current_user.merchant_id,
        ProductVariant.deleted_at.is_(None)
    ).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found.")

    variant.sku = data.sku
    variant.barcode = data.barcode
    variant.mrp = data.mrp
    variant.selling_price = data.selling_price
    variant.cost_price = data.cost_price

    db.commit()
    db.refresh(variant)
    return {"data": format_variant(variant)}

@router.delete("/variants/{variant_id}")
def delete_variant(
    variant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    variant = db.query(ProductVariant).join(Product).filter(
        ProductVariant.id == variant_id,
        Product.merchant_id == current_user.merchant_id,
        ProductVariant.deleted_at.is_(None)
    ).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found.")

    variant.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "Variant deleted successfully."}
