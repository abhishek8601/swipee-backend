from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.order import Order, OrderItem
from app.models.inventory import Inventory
from app.services.inventory_service import InventoryService
from app.core.enums import MovementType

router = APIRouter(prefix="/merchant", tags=["merchant-orders"])

class UpdateItemStatusSchema(BaseModel):
    status: str  # confirmed, processing, shipped, delivered

class CancelItemSchema(BaseModel):
    reason: Optional[str] = "Cancelled by merchant"

def format_order_item(item: OrderItem) -> dict:
    return {
        "id": item.id,
        "order_id": item.order_id,
        "product_name": item.product_name,
        "variant_sku": item.variant_sku,
        "size_name": item.size_name,
        "colour_name": item.colour_name,
        "quantity": item.quantity,
        "mrp": float(item.mrp),
        "unit_price": float(item.unit_price),
        "total_amount": float(item.total_amount),
        "commission_rate": float(item.commission_rate),
        "commission_amount": float(item.commission_amount),
        "status": item.status,
        "shipped_at": item.shipped_at.isoformat() if item.shipped_at else None,
        "delivered_at": item.delivered_at.isoformat() if item.delivered_at else None,
        "cancelled_at": item.cancelled_at.isoformat() if item.cancelled_at else None,
        "cancel_reason": item.cancel_reason,
    }

def format_merchant_order(order: Order, merchant_id: int) -> dict:
    my_items = [item for item in order.items if item.merchant_id == merchant_id]
    subtotal = sum(float(i.total_amount) for i in my_items)
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.shipping_name or (order.customer.name if order.customer else None),
        "customer_phone": order.shipping_phone or (order.customer.phone if order.customer else None),
        "status": order.status,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "merchant_subtotal": subtotal,
        "currency": order.currency,
        "shipping_address": {
            "name": order.shipping_name,
            "address_line1": order.shipping_address_line1,
            "address_line2": order.shipping_address_line2,
            "city": order.shipping_city,
            "state": order.shipping_state,
            "postal_code": order.shipping_postal_code,
        },
        "items": [format_order_item(i) for i in my_items],
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }

@router.get("/orders")
def list_merchant_orders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Find orders containing items for this merchant
    orders = db.query(Order).join(OrderItem).filter(
        OrderItem.merchant_id == current_user.merchant_id
    ).distinct().order_by(Order.created_at.desc()).all()

    return {"data": [format_merchant_order(o, current_user.merchant_id) for o in orders]}

@router.get("/orders/{order_id}")
def show_merchant_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    order = db.query(Order).join(OrderItem).filter(
        Order.id == order_id,
        OrderItem.merchant_id == current_user.merchant_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    return {"data": format_merchant_order(order, current_user.merchant_id)}

@router.post("/order-items/{item_id}/status")
def update_item_status(
    item_id: int,
    data: UpdateItemStatusSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    item = db.query(OrderItem).filter(
        OrderItem.id == item_id,
        OrderItem.merchant_id == current_user.merchant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Order line item not found.")

    new_status = data.status.lower()
    allowed = ["confirmed", "processing", "shipped", "delivered"]
    if new_status not in allowed:
        raise HTTPException(status_code=422, detail=f"Status must be one of: {', '.join(allowed)}")

    item.status = new_status
    if new_status == "shipped":
        item.shipped_at = datetime.utcnow()
        # Reduce on_hand and reserved in inventory
        if item.warehouse_id:
            inv = db.query(Inventory).filter(
                Inventory.product_variant_id == item.product_variant_id,
                Inventory.warehouse_id == item.warehouse_id
            ).first()
            if inv:
                # Dispatched: release reservation and decrease physical stock
                if inv.reserved >= item.quantity:
                    inv.reserved -= item.quantity
                if inv.on_hand >= item.quantity:
                    inv.on_hand -= item.quantity
    elif new_status == "delivered":
        item.delivered_at = datetime.utcnow()

    db.commit()
    db.refresh(item)
    return {"data": format_order_item(item)}

@router.post("/order-items/{item_id}/cancel")
def cancel_order_item(
    item_id: int,
    data: CancelItemSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    item = db.query(OrderItem).filter(
        OrderItem.id == item_id,
        OrderItem.merchant_id == current_user.merchant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Order line item not found.")

    if item.status in ("shipped", "delivered", "cancelled"):
        raise HTTPException(status_code=422, detail=f"Cannot cancel item in '{item.status}' status.")

    item.status = "cancelled"
    item.cancelled_at = datetime.utcnow()
    item.cancel_reason = data.reason

    # Unreserve stock
    if item.warehouse_id:
        inv = db.query(Inventory).filter(
            Inventory.product_variant_id == item.product_variant_id,
            Inventory.warehouse_id == item.warehouse_id
        ).first()
        if inv:
            InventoryService.unreserve(
                db=db,
                inventory=inv,
                quantity=item.quantity,
                actor=current_user,
                reason="Order item cancelled"
            )

    db.commit()
    db.refresh(item)
    return {"data": format_order_item(item)}
