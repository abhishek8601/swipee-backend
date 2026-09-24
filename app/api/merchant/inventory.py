from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.inventory import Inventory, InventoryMovement, Warehouse
from app.models.product import ProductVariant, Product
from app.services.inventory_service import InventoryService
from app.core.enums import MovementType

router = APIRouter(prefix="/merchant/inventory", tags=["merchant-inventory"])

class RestockSchema(BaseModel):
    quantity: int
    reason: Optional[str] = "Restock"

class AdjustSchema(BaseModel):
    quantity: int  # new on_hand count
    reason: Optional[str] = "Physical stock count"

class ThresholdSchema(BaseModel):
    low_stock_threshold: int
    safety_stock: Optional[int] = 0

def format_inventory_row(inv: Inventory) -> dict:
    variant = inv.variant
    product = variant.product if variant else None
    return {
        "id": inv.id,
        "product_variant_id": inv.product_variant_id,
        "product_name": product.name if product else None,
        "product_slug": product.slug if product else None,
        "sku": variant.sku if variant else None,
        "size": variant.size_value.label if variant and variant.size_value else None,
        "colour": variant.colour_value.label if variant and variant.colour_value else None,
        "warehouse_id": inv.warehouse_id,
        "warehouse_name": inv.warehouse.name if inv.warehouse else None,
        "on_hand": inv.on_hand,
        "reserved": inv.reserved,
        "available": inv.on_hand - inv.reserved,
        "low_stock_threshold": inv.low_stock_threshold,
        "safety_stock": inv.safety_stock,
        "is_low_stock": (inv.on_hand - inv.reserved) <= inv.low_stock_threshold,
        "last_movement_at": inv.last_movement_at.isoformat() if inv.last_movement_at else None,
    }

@router.get("")
def list_inventory(
    warehouse_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Inventory).join(Warehouse).filter(Warehouse.merchant_id == current_user.merchant_id)

    if warehouse_id:
        query = query.filter(Inventory.warehouse_id == warehouse_id)

    if search:
        s = f"%{search}%"
        query = query.join(ProductVariant).join(Product).filter(
            (Product.name.ilike(s)) | (ProductVariant.sku.ilike(s))
        )

    rows = query.all()
    return {"data": [format_inventory_row(r) for r in rows]}

@router.get("/low-stock")
def list_low_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    rows = db.query(Inventory).join(Warehouse).filter(
        Warehouse.merchant_id == current_user.merchant_id,
        (Inventory.on_hand - Inventory.reserved) <= Inventory.low_stock_threshold
    ).all()
    return {"data": [format_inventory_row(r) for r in rows]}

@router.get("/{inventory_id}/movements")
def list_inventory_movements(
    inventory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    inv = db.query(Inventory).join(Warehouse).filter(
        Inventory.id == inventory_id,
        Warehouse.merchant_id == current_user.merchant_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory row not found.")

    movements = db.query(InventoryMovement).filter(
        InventoryMovement.inventory_id == inv.id
    ).order_by(InventoryMovement.created_at.desc()).all()

    return {
        "data": [
            {
                "id": m.id,
                "type": m.type,
                "type_label": m.type_enum.label,
                "affects": m.affects,
                "quantity_change": m.quantity_change,
                "on_hand_after": m.on_hand_after,
                "reserved_after": m.reserved_after,
                "reason": m.reason,
                "actor_name": m.actor.name if m.actor else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in movements
        ]
    }

@router.post("/{inventory_id}/restock")
def restock(
    inventory_id: int,
    data: RestockSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    inv = db.query(Inventory).join(Warehouse).filter(
        Inventory.id == inventory_id,
        Warehouse.merchant_id == current_user.merchant_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory row not found.")

    InventoryService.increase(
        db=db,
        inventory=inv,
        quantity=data.quantity,
        type_=MovementType.RESTOCK,
        actor=current_user,
        reason=data.reason
    )
    db.commit()
    db.refresh(inv)
    return {"data": format_inventory_row(inv)}

@router.post("/{inventory_id}/adjust")
def adjust_stock(
    inventory_id: int,
    data: AdjustSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    inv = db.query(Inventory).join(Warehouse).filter(
        Inventory.id == inventory_id,
        Warehouse.merchant_id == current_user.merchant_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory row not found.")

    InventoryService.adjust(
        db=db,
        inventory=inv,
        new_on_hand=data.quantity,
        actor=current_user,
        reason=data.reason
    )
    db.commit()
    db.refresh(inv)
    return {"data": format_inventory_row(inv)}

@router.put("/{inventory_id}/thresholds")
def update_thresholds(
    inventory_id: int,
    data: ThresholdSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    inv = db.query(Inventory).join(Warehouse).filter(
        Inventory.id == inventory_id,
        Warehouse.merchant_id == current_user.merchant_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory row not found.")

    inv.low_stock_threshold = data.low_stock_threshold
    inv.safety_stock = data.safety_stock or 0
    db.commit()
    db.refresh(inv)
    return {"data": format_inventory_row(inv)}
