from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.merchant import Merchant
from app.models.product import Product, ProductVariant
from app.models.inventory import Inventory
from app.models.order import Order, OrderItem
from app.core.enums import ProductStatus, MerchantStatus

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
                "low_stock_items": low_stock_count,
            },
            "recent_orders": [],
            "pipeline": {
                "draft": draft_products,
                "pending": pending_products,
                "approved": approved_products,
            }
        }
    else:
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
