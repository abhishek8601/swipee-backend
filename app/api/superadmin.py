"""Super-admin-only platform operations using the project's existing models."""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.admin.orders import format_admin_order
from app.api.merchant.products import format_product_detail, format_product_list_item
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.core.enums import MerchantStatus, ProductStatus, UserRole
from app.models.ai_model import AiModel, ProductTryOn
from app.models.merchant import Merchant
from app.models.misc import AuditLog, Payout
from app.models.order import Order, OrderItem
from app.models.product import Product, ProductApprovalHistory
from app.models.taxonomy import Category
from app.models.user import User

router = APIRouter(prefix="/superadmin", tags=["superadmin"])


class ReasonInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class CategoryInput(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: Optional[str] = None
    image_path: Optional[str] = None
    is_active: bool = True


def success(message: str, data=None, meta=None):
    payload = {"success": True, "message": message, "data": data if data is not None else {}}
    if meta is not None:
        payload["meta"] = meta
    return payload


def page(query, page_number: int, per_page: int):
    page_number, per_page = max(page_number, 1), min(max(per_page, 1), 100)
    total = query.order_by(None).count()
    rows = query.offset((page_number - 1) * per_page).limit(per_page).all()
    return rows, {"page": page_number, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page}


def log(db: Session, actor: User, action: str, target, request: Request, description: str):
    db.add(AuditLog(
        user_id=actor.id, action=action, auditable_type=type(target).__name__, auditable_id=target.id,
        new_values={"description": description}, ip_address=request.client.host if request.client else None,
    ))


def merchant_data(m: Merchant, detailed: bool = False) -> dict:
    data = {
        "id": m.id, "legal_name": m.legal_name, "display_name": m.display_name, "slug": m.slug,
        "email": m.email, "phone": m.phone, "business_type": m.business_type, "gstin": m.gstin,
        "pan": m.pan, "cin": m.cin, "status": m.status, "status_label": m.status_label,
        "verification_reason": m.status_reason, "can_trade": m.can_trade,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
    if detailed:
        data.update({
            "description": m.description, "website": m.website,
            "addresses": [{"id": a.id, "type": a.type, "address_line1": a.address_line1, "address_line2": a.address_line2, "city": a.city, "state": a.state, "postal_code": a.postal_code, "country": a.country} for a in m.addresses],
            "bank_accounts": [{"id": b.id, "account_holder_name": b.account_holder_name, "account_number": f"****{b.account_number[-4:]}", "ifsc_code": b.ifsc_code, "bank_name": b.bank_name, "is_verified": bool(b.is_verified)} for b in m.bank_accounts],
            "documents": [{"id": d.id, "document_type": d.document_type, "file_url": f"/storage/{d.file_path}", "status": d.status, "rejection_reason": d.rejection_reason, "created_at": d.created_at.isoformat() if d.created_at else None} for d in m.documents],
            "products": [{"id": p.id, "name": p.name, "status": p.status, "selling_price": float(p.selling_price)} for p in m.products if p.deleted_at is None],
        })
    return data


def user_data(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "gender": user.gender, "role": user.role, "status": user.status, "merchant_id": user.merchant_id, "created_at": user.created_at.isoformat() if user.created_at else None}


def reel_data(reel: ProductTryOn) -> dict:
    return {"id": reel.id, "merchant": {"id": reel.merchant_id, "name": reel.merchant.display_name if reel.merchant else None}, "product": {"id": reel.product_id, "name": reel.product.name if reel.product else None}, "ai_model": {"id": reel.ai_model_id, "name": reel.ai_model.name if reel.ai_model else None}, "status": reel.status, "is_published": bool(reel.is_published), "result_url": f"/storage/{reel.result_path}" if reel.result_path else None, "error_message": reel.error_message, "created_at": reel.created_at.isoformat() if reel.created_at else None}


def payout_data(p: Payout) -> dict:
    return {"id": p.id, "payout_number": p.payout_number, "merchant": {"id": p.merchant_id, "name": p.merchant.display_name if p.merchant else None}, "period_start": p.period_start.isoformat(), "period_end": p.period_end.isoformat(), "gross_sales": float(p.gross_sales or 0), "commission_total": float(p.commission_total or 0), "tax_total": float(p.tax_total or 0), "net_payout": float(p.net_payout or 0), "status": p.status}


def merchant_or_404(db: Session, merchant_id: int) -> Merchant:
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not merchant:
        raise HTTPException(404, "Merchant not found.")
    return merchant


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    total_sales = db.query(func.sum(Order.grand_total)).filter(Order.payment_status == "paid").scalar() or 0
    commission = db.query(func.sum(OrderItem.commission_amount)).scalar() or 0
    ai_usage = db.query(ProductTryOn).count()
    return success("Dashboard retrieved successfully.", {
        "total_users": db.query(User).count(), "total_buyers": db.query(User).filter(User.role.in_((UserRole.BUYER.value, UserRole.CUSTOMER.value))).count(),
        "total_merchants": db.query(Merchant).filter(Merchant.deleted_at.is_(None)).count(),
        "pending_merchant_verifications": db.query(Merchant).filter(Merchant.status.in_((MerchantStatus.PENDING.value, MerchantStatus.UNDER_REVIEW.value))).count(),
        "approved_merchants": db.query(Merchant).filter(Merchant.status == MerchantStatus.APPROVED.value).count(),
        "rejected_merchants": db.query(Merchant).filter(Merchant.status == MerchantStatus.REJECTED.value).count(),
        "total_products": db.query(Product).filter(Product.deleted_at.is_(None)).count(), "active_products": db.query(Product).filter(Product.is_active.is_(True), Product.deleted_at.is_(None)).count(),
        "total_reels": ai_usage, "published_reels": db.query(ProductTryOn).filter(ProductTryOn.is_published.is_(True)).count(), "pending_reels": db.query(ProductTryOn).filter(ProductTryOn.status == "completed", ProductTryOn.is_published.is_(False)).count(),
        "total_orders": db.query(Order).count(), "completed_orders": db.query(Order).filter(Order.status == "delivered").count(), "cancelled_orders": db.query(Order).filter(Order.status.in_(("cancelled", "returned"))).count(),
        "total_sales": float(total_sales), "platform_commission": float(commission), "merchant_payouts": float(db.query(func.sum(Payout.net_payout)).filter(Payout.status == "paid").scalar() or 0),
        "ai_generation_usage": ai_usage, "ai_generation_cost": float(db.query(func.sum(ProductTryOn.cost_usd)).scalar() or 0),
    })


@router.get("/merchants")
def list_merchants(search: Optional[str] = None, status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(Merchant).filter(Merchant.deleted_at.is_(None))
    if status: query = query.filter(Merchant.status == status)
    if search:
        term = f"%{search}%"; query = query.filter(or_(Merchant.display_name.ilike(term), Merchant.legal_name.ilike(term), Merchant.email.ilike(term), Merchant.phone.ilike(term)))
    rows, meta = page(query.order_by(Merchant.created_at.desc()), page_number, per_page)
    return success("Merchants retrieved successfully.", [merchant_data(row) for row in rows], meta)


@router.get("/merchants/{merchant_id}")
def get_merchant(merchant_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    merchant = merchant_or_404(db, merchant_id)
    data = merchant_data(merchant, True)
    data["reels"] = [reel_data(r) for r in db.query(ProductTryOn).filter(ProductTryOn.merchant_id == merchant.id).all()]
    data["orders"] = [format_admin_order(o) for o in db.query(Order).join(OrderItem).filter(OrderItem.merchant_id == merchant.id).distinct().all()]
    data["payouts"] = [payout_data(p) for p in db.query(Payout).filter(Payout.merchant_id == merchant.id).all()]
    return success("Merchant retrieved successfully.", data)


def set_merchant_status(merchant_id: int, value: str, action: str, message: str, request: Request, reason: Optional[ReasonInput], db: Session, admin: User):
    merchant = merchant_or_404(db, merchant_id)
    merchant.status, merchant.status_reason, merchant.reviewed_by, merchant.reviewed_at = value, reason.reason if reason else None, admin.id, datetime.utcnow()
    if value == MerchantStatus.APPROVED.value: merchant.onboarded_at = datetime.utcnow()
    log(db, admin, action, merchant, request, reason.reason if reason else message); db.commit(); db.refresh(merchant)
    return success(message, merchant_data(merchant, True))


@router.post("/merchants/{merchant_id}/approve")
def approve_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return set_merchant_status(merchant_id, MerchantStatus.APPROVED.value, "superadmin.merchant_approved", "Merchant approved successfully.", request, None, db, admin)


@router.post("/merchants/{merchant_id}/reject")
def reject_merchant(merchant_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return set_merchant_status(merchant_id, MerchantStatus.REJECTED.value, "superadmin.merchant_rejected", "Merchant rejected successfully.", request, body, db, admin)


@router.post("/merchants/{merchant_id}/suspend")
def suspend_merchant(merchant_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return set_merchant_status(merchant_id, MerchantStatus.SUSPENDED.value, "superadmin.merchant_suspended", "Merchant suspended successfully.", request, body, db, admin)


@router.post("/merchants/{merchant_id}/activate")
def activate_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return set_merchant_status(merchant_id, MerchantStatus.APPROVED.value, "superadmin.merchant_activated", "Merchant activated successfully.", request, None, db, admin)


@router.get("/merchant-verifications")
def verifications(status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(Merchant).filter(Merchant.deleted_at.is_(None))
    if status: query = query.filter(Merchant.status == status)
    rows, meta = page(query.order_by(Merchant.updated_at.desc()), page_number, per_page)
    return success("Merchant verifications retrieved successfully.", [merchant_data(row, True) for row in rows], meta)


@router.get("/merchant-verifications/{merchant_id}")
def verification_detail(merchant_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return success("Merchant verification retrieved successfully.", merchant_data(merchant_or_404(db, merchant_id), True))


@router.post("/merchant-verifications/{merchant_id}/approve")
def approve_verification(merchant_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return approve_merchant(merchant_id, request, db, admin)


@router.post("/merchant-verifications/{merchant_id}/reject")
def reject_verification(merchant_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return reject_merchant(merchant_id, body, request, db, admin)


@router.get("/users")
def list_users(role: Optional[str] = None, status: Optional[str] = None, search: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(User).filter(User.deleted_at.is_(None))
    if role: query = query.filter(User.role == role)
    if status: query = query.filter(User.status == status)
    if search:
        term = f"%{search}%"; query = query.filter(or_(User.name.ilike(term), User.email.ilike(term), User.phone.ilike(term)))
    rows, meta = page(query.order_by(User.created_at.desc()), page_number, per_page)
    return success("Users retrieved successfully.", [user_data(row) for row in rows], meta)


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user: raise HTTPException(404, "User not found.")
    return success("User retrieved successfully.", user_data(user))


def change_user_status(user_id: int, target_status: str, request: Request, db: Session, admin: User):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user: raise HTTPException(404, "User not found.")
    if user.id == admin.id: raise HTTPException(422, "You cannot change your own account status.")
    if user.role == UserRole.SUPER_ADMIN.value: raise HTTPException(422, "Super admin accounts cannot be changed through this endpoint.")
    user.status = target_status; log(db, admin, f"superadmin.user_{target_status}", user, request, f"User {target_status}"); db.commit()
    return success(f"User {target_status} successfully.", user_data(user))


@router.post("/users/{user_id}/activate")
def activate_user(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return change_user_status(user_id, "active", request, db, admin)


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return change_user_status(user_id, "suspended", request, db, admin)


@router.get("/products")
def list_products(search: Optional[str] = None, merchant_id: Optional[int] = None, category_id: Optional[int] = None, status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(Product).filter(Product.deleted_at.is_(None))
    if merchant_id: query = query.filter(Product.merchant_id == merchant_id)
    if category_id: query = query.filter(Product.category_id == category_id)
    if status: query = query.filter(Product.status == status)
    if search:
        term = f"%{search}%"; query = query.filter(or_(Product.name.ilike(term), Product.style_code.ilike(term)))
    rows, meta = page(query.order_by(Product.created_at.desc()), page_number, per_page)
    return success("Products retrieved successfully.", [{**format_product_list_item(p), "merchant": {"id": p.merchant_id, "name": p.merchant.display_name if p.merchant else None}} for p in rows], meta)


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not product: raise HTTPException(404, "Product not found.")
    return success("Product retrieved successfully.", {**format_product_detail(product), "merchant": {"id": product.merchant_id, "name": product.merchant.display_name if product.merchant else None}})


def moderate_product(product_id: int, target_status: str, active: Optional[bool], action: str, message: str, body: Optional[ReasonInput], request: Request, db: Session, admin: User):
    product = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not product: raise HTTPException(404, "Product not found.")
    before = product.status; product.status = target_status
    if active is not None: product.is_active = active
    product.rejection_reason = body.reason if body else None
    if target_status == ProductStatus.APPROVED.value: product.approved_at, product.approved_by = datetime.utcnow(), admin.id
    db.add(ProductApprovalHistory(product_id=product.id, from_status=before, to_status=target_status, reason=body.reason if body else message, action_by=admin.id))
    log(db, admin, action, product, request, body.reason if body else message); db.commit()
    return success(message, format_product_detail(product))


@router.post("/products/{product_id}/approve")
def approve_product(product_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_product(product_id, ProductStatus.APPROVED.value, True, "superadmin.product_approved", "Product approved successfully.", None, request, db, admin)


@router.post("/products/{product_id}/reject")
def reject_product(product_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_product(product_id, ProductStatus.REJECTED.value, False, "superadmin.product_rejected", "Product rejected successfully.", body, request, db, admin)


@router.post("/products/{product_id}/disable")
def disable_product(product_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_product(product_id, ProductStatus.REJECTED.value, False, "superadmin.product_disabled", "Product disabled successfully.", body, request, db, admin)


@router.post("/products/{product_id}/enable")
def enable_product(product_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_product(product_id, ProductStatus.APPROVED.value, True, "superadmin.product_enabled", "Product enabled successfully.", None, request, db, admin)


@router.get("/reels")
def list_reels(merchant_id: Optional[int] = None, status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(ProductTryOn)
    if merchant_id: query = query.filter(ProductTryOn.merchant_id == merchant_id)
    if status: query = query.filter(ProductTryOn.status == status)
    rows, meta = page(query.order_by(ProductTryOn.created_at.desc()), page_number, per_page)
    return success("Reels retrieved successfully.", [reel_data(row) for row in rows], meta)


@router.get("/reels/{reel_id}")
def get_reel(reel_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    reel = db.query(ProductTryOn).filter(ProductTryOn.id == reel_id).first()
    if not reel: raise HTTPException(404, "Reel not found.")
    return success("Reel retrieved successfully.", reel_data(reel))


def moderate_reel(reel_id: int, publish: bool, body: Optional[ReasonInput], action: str, message: str, request: Request, db: Session, admin: User):
    reel = db.query(ProductTryOn).filter(ProductTryOn.id == reel_id).first()
    if not reel: raise HTTPException(404, "Reel not found.")
    reel.is_published = publish
    if publish: reel.published_at, reel.published_by, reel.error_message = datetime.utcnow(), admin.id, None
    elif body: reel.error_message = body.reason
    log(db, admin, action, reel, request, body.reason if body else message); db.commit()
    return success(message, reel_data(reel))


@router.post("/reels/{reel_id}/approve")
def approve_reel(reel_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_reel(reel_id, True, None, "superadmin.reel_approved", "Reel approved successfully.", request, db, admin)


@router.post("/reels/{reel_id}/reject")
def reject_reel(reel_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_reel(reel_id, False, body, "superadmin.reel_rejected", "Reel rejected successfully.", request, db, admin)


@router.post("/reels/{reel_id}/disable")
def disable_reel(reel_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return moderate_reel(reel_id, False, body, "superadmin.reel_disabled", "Reel disabled successfully.", request, db, admin)


@router.get("/orders")
def list_orders(search: Optional[str] = None, merchant_id: Optional[int] = None, buyer_email: Optional[str] = None, status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(Order)
    if merchant_id: query = query.join(OrderItem).filter(OrderItem.merchant_id == merchant_id).distinct()
    if buyer_email: query = query.join(Order.customer).filter_by(email=buyer_email)
    if status: query = query.filter(Order.status == status)
    if search: query = query.filter(Order.order_number.ilike(f"%{search}%"))
    rows, meta = page(query.order_by(Order.created_at.desc()), page_number, per_page)
    return success("Orders retrieved successfully.", [format_admin_order(row) for row in rows], meta)


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order: raise HTTPException(404, "Order not found.")
    return success("Order retrieved successfully.", format_admin_order(order))


@router.get("/payouts")
def list_payouts(merchant_id: Optional[int] = None, status: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(Payout)
    if merchant_id: query = query.filter(Payout.merchant_id == merchant_id)
    if status: query = query.filter(Payout.status == status)
    rows, meta = page(query.order_by(Payout.period_end.desc()), page_number, per_page)
    return success("Payouts retrieved successfully.", [payout_data(row) for row in rows], meta)


@router.get("/payouts/{payout_id}")
def get_payout(payout_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    payout = db.query(Payout).filter(Payout.id == payout_id).first()
    if not payout: raise HTTPException(404, "Payout not found.")
    return success("Payout retrieved successfully.", payout_data(payout))


def update_payout(payout_id: int, target_status: str, action: str, message: str, body: Optional[ReasonInput], request: Request, db: Session, admin: User):
    payout = db.query(Payout).filter(Payout.id == payout_id).first()
    if not payout: raise HTTPException(404, "Payout not found.")
    payout.status, payout.processed_by, payout.processed_at = target_status, admin.id, datetime.utcnow()
    log(db, admin, action, payout, request, body.reason if body else message); db.commit()
    return success(message, payout_data(payout))


@router.post("/payouts/{payout_id}/approve")
def approve_payout(payout_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return update_payout(payout_id, "approved", "superadmin.payout_approved", "Payout approved successfully.", None, request, db, admin)


@router.post("/payouts/{payout_id}/reject")
def reject_payout(payout_id: int, body: ReasonInput, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return update_payout(payout_id, "failed", "superadmin.payout_rejected", "Payout rejected successfully.", body, request, db, admin)


@router.get("/commissions")
def commissions(merchant_id: Optional[int] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(OrderItem)
    if merchant_id: query = query.filter(OrderItem.merchant_id == merchant_id)
    rows, meta = page(query.order_by(OrderItem.created_at.desc()), page_number, per_page)
    data = [{"order_id": item.order_id, "merchant": {"id": item.merchant_id, "name": item.merchant.display_name if item.merchant else None}, "product_name": item.product_name, "order_amount": float(item.total_amount), "commission_percentage": float(item.commission_rate or 0), "commission_amount": float(item.commission_amount or 0), "merchant_earning": float((item.total_amount or 0) - (item.commission_amount or 0)), "order_status": item.status} for item in rows]
    return success("Commission report retrieved successfully.", data, meta)


@router.get("/audit-logs")
def audit_logs(action: Optional[str] = None, page_number: int = Query(1, alias="page"), per_page: int = 20, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    query = db.query(AuditLog).join(User, AuditLog.user_id == User.id).filter(User.role == UserRole.SUPER_ADMIN.value)
    if action: query = query.filter(AuditLog.action == action)
    rows, meta = page(query.order_by(AuditLog.created_at.desc()), page_number, per_page)
    return success("Audit logs retrieved successfully.", [{"id": row.id, "super_admin": {"id": row.user_id, "name": row.user.name if row.user else None}, "action": row.action, "target_type": row.auditable_type, "target_id": row.auditable_id, "description": (row.new_values or {}).get("description"), "ip_address": row.ip_address, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], meta)


@router.get("/reports/sales")
def sales_report(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.query(func.date(Order.created_at).label("date"), func.count(Order.id), func.coalesce(func.sum(Order.grand_total), 0)).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at)).all()
    return success("Sales report retrieved successfully.", [{"date": str(day), "orders": count, "sales": float(total)} for day, count, total in rows])


@router.get("/reports/merchants")
def merchants_report(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.query(Merchant.status, func.count(Merchant.id)).group_by(Merchant.status).all()
    return success("Merchant report retrieved successfully.", [{"status": status, "count": count} for status, count in rows])


@router.get("/reports/users")
def users_report(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.query(User.role, User.status, func.count(User.id)).group_by(User.role, User.status).all()
    return success("User report retrieved successfully.", [{"role": role, "status": status, "count": count} for role, status, count in rows])


@router.get("/reports/orders")
def orders_report(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.query(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.grand_total), 0)).group_by(Order.status).all()
    return success("Order report retrieved successfully.", [{"status": status, "count": count, "sales": float(total)} for status, count, total in rows])


@router.get("/reports/ai-usage")
def ai_usage_report(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.query(ProductTryOn.provider, ProductTryOn.status, func.count(ProductTryOn.id), func.coalesce(func.sum(ProductTryOn.cost_usd), 0)).group_by(ProductTryOn.provider, ProductTryOn.status).all()
    return success("AI usage report retrieved successfully.", [{"provider": provider, "status": status, "generations": count, "cost": float(cost)} for provider, status, count, cost in rows])
