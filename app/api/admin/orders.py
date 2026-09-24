from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.models.user import User
from app.models.order import Order
from app.core.permissions import Permissions

router = APIRouter(prefix="/admin/orders", tags=["admin-orders"])

def format_admin_order(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer": {
            "id": order.customer_id,
            "name": order.customer.name if order.customer else None,
            "email": order.customer.email if order.customer else None,
        } if order.customer else None,
        "status": order.status,
        "items_subtotal": float(order.items_subtotal),
        "discount_total": float(order.discount_total),
        "tax_total": float(order.tax_total),
        "shipping_total": float(order.shipping_total),
        "grand_total": float(order.grand_total),
        "currency": order.currency,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "items": [
            {
                "id": item.id,
                "merchant_id": item.merchant_id,
                "merchant_name": item.merchant.display_name if item.merchant else None,
                "product_name": item.product_name,
                "variant_sku": item.variant_sku,
                "quantity": item.quantity,
                "total_amount": float(item.total_amount),
                "commission_amount": float(item.commission_amount),
                "status": item.status,
            }
            for item in order.items
        ],
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }

@router.get("")
def list_admin_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.ORDER_VIEW_ANY))
):
    query = db.query(Order)
    if status_filter:
        query = query.filter(Order.status == status_filter)

    orders = query.order_by(Order.created_at.desc()).all()
    return {"data": [format_admin_order(o) for o in orders]}

@router.get("/{order_id}")
def show_admin_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.ORDER_VIEW_ANY))
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return {"data": format_admin_order(order)}
