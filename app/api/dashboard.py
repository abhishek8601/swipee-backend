from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.merchant import Merchant
from app.models.product import Product, ProductVariant
from app.models.inventory import Inventory
from app.models.order import Customer, Order, OrderItem
from app.models.ai_model import ProductTryOn
from app.models.misc import Payout
from app.core.enums import ProductStatus, MerchantStatus, UserRole

router = APIRouter(tags=["dashboard"])

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.is_merchant_side:
        merchant_id = current_user.merchant_id

        total_products = db.query(Product).filter(Product.merchant_id == merchant_id, Product.deleted_at.is_(None)).count()
        approved_products = db.query(Product).filter(Product.merchant_id == merchant_id, Product.status == ProductStatus.APPROVED.value, Product.deleted_at.is_(None)).count()
        pending_products = db.query(Product).filter(Product.merchant_id == merchant_id, Product.status == ProductStatus.PENDING_REVIEW.value, Product.deleted_at.is_(None)).count()
        draft_products = db.query(Product).filter(Product.merchant_id == merchant_id, Product.status == ProductStatus.DRAFT.value, Product.deleted_at.is_(None)).count()

        # Orders for this merchant
        order_items = db.query(OrderItem).filter(OrderItem.merchant_id == merchant_id).all()
        total_orders = len(set(item.order_id for item in order_items))
        revenue = sum(float(item.total_amount) for item in order_items if item.status != "cancelled")
        published_reels = db.query(ProductTryOn).filter(
            ProductTryOn.merchant_id == merchant_id,
            ProductTryOn.is_published.is_(True),
        ).count()
        pending_payout = db.query(func.sum(Payout.net_payout)).filter(
            Payout.merchant_id == merchant_id,
            Payout.status.in_(("pending", "approved", "processing")),
        ).scalar() or 0
        paid_out = db.query(func.sum(Payout.net_payout)).filter(
            Payout.merchant_id == merchant_id,
            Payout.status == "paid",
        ).scalar() or 0

        # Low stock count
        low_stock_count = db.query(Inventory).join(ProductVariant).join(Product).filter(
            Product.merchant_id == merchant_id,
            (Inventory.on_hand - Inventory.reserved) <= Inventory.low_stock_threshold
        ).count()

        return {
            "role": "merchant",
            "kpis": {
                "total_products": total_products,
                "approved_products": approved_products,
                "pending_products": pending_products,
                "draft_products": draft_products,
                "total_orders": total_orders,
                "revenue": revenue,
                "published_reels": published_reels,
                "low_stock_items": low_stock_count,
                "pending_payout": float(pending_payout),
                "paid_out": float(paid_out),
            },
            "recent_orders": [],
            "pipeline": {
                "draft": draft_products,
                "pending": pending_products,
                "approved": approved_products,
            }
        }

    if current_user.is_customer:
        # Customer records are currently linked to user accounts by email.
        customer = db.query(Customer).filter(Customer.email == current_user.email).first()
        orders_query = db.query(Order)
        if customer:
            orders_query = orders_query.filter(Order.customer_id == customer.id)
        else:
            # A customer account can exist before its customer profile/order history.
            orders_query = orders_query.filter(Order.id.is_(None))

        orders = orders_query.order_by(Order.created_at.desc()).all()
        cancelled_statuses = ("cancelled", "returned")
        active_statuses = ("pending", "confirmed", "processing", "shipped")

        total_spent = sum(
            float(order.grand_total or 0)
            for order in orders
            if order.status not in cancelled_statuses
        )

        return {
            "role": current_user.role,
            "kpis": {
                "total_orders": len(orders),
                "active_orders": sum(order.status in active_statuses for order in orders),
                "delivered_orders": sum(order.status == "delivered" for order in orders),
                "cancelled_orders": sum(order.status in cancelled_statuses for order in orders),
                "total_spent": total_spent,
            },
            "recent_orders": [
                {
                    "id": order.id,
                    "order_number": order.order_number,
                    "status": order.status,
                    "payment_status": order.payment_status,
                    "grand_total": float(order.grand_total or 0),
                    "currency": order.currency,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                }
                for order in orders[:5]
            ],
        }

    if current_user.is_platform_side:
        # Platform Admin / Super Admin
        total_merchants = db.query(Merchant).filter(Merchant.deleted_at.is_(None)).count()
        pending_merchants = db.query(Merchant).filter(Merchant.status == MerchantStatus.UNDER_REVIEW.value, Merchant.deleted_at.is_(None)).count()
        approved_merchants = db.query(Merchant).filter(Merchant.status == MerchantStatus.APPROVED.value, Merchant.deleted_at.is_(None)).count()

        total_products = db.query(Product).filter(Product.deleted_at.is_(None)).count()
        queue_count = db.query(Product).filter(Product.status == ProductStatus.PENDING_REVIEW.value, Product.deleted_at.is_(None)).count()

        total_orders = db.query(Order).count()
        gmv = db.query(func.sum(Order.grand_total)).scalar() or 0.00

        return {
            "role": current_user.role,
            "kpis": {
                "total_merchants": total_merchants,
                "pending_merchants": pending_merchants,
                "approved_merchants": approved_merchants,
                "catalog_review_queue": queue_count,
                "total_products": total_products,
                "total_orders": total_orders,
                "gmv": float(gmv),
            },
            "pipeline": {
                "merchants_pending": pending_merchants,
                "products_pending_review": queue_count,
            }
        }

    # Do not expose platform metrics to an unrecognised role.
    return {
        "role": current_user.role,
        "kpis": {},
        "recent_orders": [],
    }
