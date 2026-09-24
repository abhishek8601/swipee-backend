from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.models.user import User
from app.models.product import Product, ProductApprovalHistory
from app.core.enums import ProductStatus
from app.core.permissions import Permissions
from app.api.merchant.products import format_product_list_item, format_product_detail

router = APIRouter(prefix="/admin/products", tags=["admin-products"])

class RejectSchema(BaseModel):
    reason: str

class BulkApproveSchema(BaseModel):
    product_ids: List[int]

@router.get("/queue")
def get_review_queue(
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_APPROVE))
):
    query = db.query(Product).filter(
        Product.status == ProductStatus.PENDING_REVIEW.value,
        Product.deleted_at.is_(None)
    )
    if search:
        s = f"%{search}%"
        query = query.filter((Product.name.ilike(s)) | (Product.style_code.ilike(s)))

    products = query.order_by(Product.submitted_at.asc()).all()
    return {
        "data": [
            {
                **format_product_list_item(p),
                "merchant": {"id": p.merchant.id, "display_name": p.merchant.display_name} if p.merchant else None,
                "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
            }
            for p in products
        ]
    }

@router.get("")
def list_all_products(
    status_filter: Optional[str] = Query(None, alias="status"),
    merchant_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_VIEW_ANY))
):
    query = db.query(Product).filter(Product.deleted_at.is_(None))
    if status_filter:
        query = query.filter(Product.status == status_filter)
    if merchant_id:
        query = query.filter(Product.merchant_id == merchant_id)
    if search:
        s = f"%{search}%"
        query = query.filter((Product.name.ilike(s)) | (Product.style_code.ilike(s)))

    products = query.order_by(Product.created_at.desc()).all()
    return {
        "data": [
            {
                **format_product_list_item(p),
                "merchant": {"id": p.merchant.id, "display_name": p.merchant.display_name} if p.merchant else None,
            }
            for p in products
        ]
    }

@router.post("/bulk-approve")
def bulk_approve_products(
    data: BulkApproveSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_APPROVE))
):
    products = db.query(Product).filter(
        Product.id.in_(data.product_ids),
        Product.status == ProductStatus.PENDING_REVIEW.value,
        Product.deleted_at.is_(None)
    ).all()

    for p in products:
        p.status = ProductStatus.APPROVED.value
        p.approved_at = datetime.utcnow()
        p.approved_by = current_user.id
        p.rejection_reason = None

        hist = ProductApprovalHistory(
            product_id=p.id,
            from_status=ProductStatus.PENDING_REVIEW.value,
            to_status=ProductStatus.APPROVED.value,
            reason="Bulk approved by admin",
            action_by=current_user.id
        )
        db.add(hist)

    db.commit()
    return {"message": f"Approved {len(products)} listings."}

@router.get("/{product_id}")
def show_admin_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_VIEW_ANY))
):
    p = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")

    res = format_product_detail(p)
    res["merchant"] = {"id": p.merchant.id, "display_name": p.merchant.display_name} if p.merchant else None
    return {"data": res}

@router.post("/{product_id}/approve")
def approve_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_APPROVE))
):
    p = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")

    from_status = p.status
    p.status = ProductStatus.APPROVED.value
    p.approved_at = datetime.utcnow()
    p.approved_by = current_user.id
    p.rejection_reason = None

    hist = ProductApprovalHistory(
        product_id=p.id,
        from_status=from_status,
        to_status=ProductStatus.APPROVED.value,
        reason="Approved by admin",
        action_by=current_user.id
    )
    db.add(hist)
    db.commit()
    return {"data": format_product_detail(p)}

@router.post("/{product_id}/reject")
def reject_product(
    product_id: int,
    data: RejectSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_APPROVE))
):
    p = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")

    from_status = p.status
    p.status = ProductStatus.REJECTED.value
    p.rejection_reason = data.reason

    hist = ProductApprovalHistory(
        product_id=p.id,
        from_status=from_status,
        to_status=ProductStatus.REJECTED.value,
        reason=data.reason,
        action_by=current_user.id
    )
    db.add(hist)
    db.commit()
    return {"data": format_product_detail(p)}

@router.post("/{product_id}/takedown")
def takedown_product(
    product_id: int,
    data: RejectSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.PRODUCT_TAKEDOWN))
):
    p = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")

    from_status = p.status
    p.status = ProductStatus.REJECTED.value
    p.is_active = False
    p.rejection_reason = data.reason

    hist = ProductApprovalHistory(
        product_id=p.id,
        from_status=from_status,
        to_status=ProductStatus.REJECTED.value,
        reason=f"Taken down by platform admin: {data.reason}",
        action_by=current_user.id
    )
    db.add(hist)
    db.commit()
    return {"data": format_product_detail(p)}
