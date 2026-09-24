import re
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import require_roles, require_permissions
from app.models.user import User
from app.models.merchant import Merchant
from app.core.enums import MerchantStatus
from app.core.permissions import Permissions

router = APIRouter(prefix="/admin/merchants", tags=["admin-merchants"])

class MerchantCreateSchema(BaseModel):
    legal_name: str
    display_name: str
    email: str
    phone: str
    business_type: Optional[str] = "proprietorship"
    gstin: Optional[str] = None
    pan: Optional[str] = None
    cin: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    default_commission_rate: Optional[float] = 15.00
    payout_cycle: Optional[str] = "weekly"
    settlement_days: Optional[int] = 7

class StatusActionSchema(BaseModel):
    reason: Optional[str] = None

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)

def format_admin_merchant(m: Merchant) -> dict:
    return {
        "id": m.id,
        "legal_name": m.legal_name,
        "display_name": m.display_name,
        "slug": m.slug,
        "email": m.email,
        "phone": m.phone,
        "logo_url": f"/storage/{m.logo_path}" if m.logo_path else None,
        "description": m.description,
        "website": m.website,
        "business_type": m.business_type,
        "gstin": m.gstin,
        "pan": m.pan,
        "cin": m.cin,
        "status": m.status,
        "status_label": m.status_label,
        "status_reason": m.status_reason,
        "can_trade": m.can_trade,
        "default_commission_rate": float(m.default_commission_rate) if m.default_commission_rate else 15.00,
        "payout_cycle": m.payout_cycle,
        "settlement_days": m.settlement_days,
        "total_products": m.total_products,
        "total_orders": m.total_orders,
        "rating": float(m.rating) if m.rating else 0.00,
        "onboarded_at": m.onboarded_at.isoformat() if m.onboarded_at else None,
        "reviewed_at": m.reviewed_at.isoformat() if m.reviewed_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }

@router.get("")
def list_merchants(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_VIEW_ANY))
):
    query = db.query(Merchant).filter(Merchant.deleted_at.is_(None))
    if status_filter:
        query = query.filter(Merchant.status == status_filter)
    if search:
        s = f"%{search}%"
        query = query.filter((Merchant.display_name.ilike(s)) | (Merchant.legal_name.ilike(s)) | (Merchant.email.ilike(s)))

    merchants = query.order_by(Merchant.created_at.desc()).all()
    return {"data": [format_admin_merchant(m) for m in merchants]}

@router.post("")
def create_merchant(
    data: MerchantCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_CREATE))
):
    if db.query(Merchant).filter(Merchant.email == data.email).first():
        raise HTTPException(status_code=422, detail="A merchant with this email already exists.")

    base_slug = slugify(data.display_name)
    slug = base_slug
    counter = 1
    while db.query(Merchant).filter(Merchant.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    m = Merchant(
        legal_name=data.legal_name,
        display_name=data.display_name,
        slug=slug,
        email=data.email,
        phone=data.phone,
        business_type=data.business_type,
        gstin=data.gstin,
        pan=data.pan,
        cin=data.cin,
        description=data.description,
        website=data.website,
        default_commission_rate=data.default_commission_rate,
        payout_cycle=data.payout_cycle,
        settlement_days=data.settlement_days,
        status=MerchantStatus.PENDING.value
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}

@router.get("/{merchant_id}")
def show_merchant(
    merchant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_VIEW))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")
    return {"data": format_admin_merchant(m)}

@router.put("/{merchant_id}")
def update_merchant(
    merchant_id: int,
    data: MerchantCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_UPDATE))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")

    for k, v in data.model_dump().items():
        setattr(m, k, v)

    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}

@router.post("/{merchant_id}/approve")
def approve_merchant(
    merchant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_APPROVE))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")

    m.status = MerchantStatus.APPROVED.value
    m.reviewed_by = current_user.id
    m.reviewed_at = datetime.utcnow()
    m.onboarded_at = datetime.utcnow()
    m.status_reason = None
    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}

@router.post("/{merchant_id}/reject")
def reject_merchant(
    merchant_id: int,
    data: StatusActionSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_APPROVE))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")

    m.status = MerchantStatus.REJECTED.value
    m.reviewed_by = current_user.id
    m.reviewed_at = datetime.utcnow()
    m.status_reason = data.reason or "KYC verification rejected"
    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}

@router.post("/{merchant_id}/suspend")
def suspend_merchant(
    merchant_id: int,
    data: StatusActionSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_SUSPEND))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")

    m.status = MerchantStatus.SUSPENDED.value
    m.status_reason = data.reason or "Account suspended by platform admin"
    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}

@router.post("/{merchant_id}/reinstate")
def reinstate_merchant(
    merchant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permissions(Permissions.MERCHANT_SUSPEND))
):
    m = db.query(Merchant).filter(Merchant.id == merchant_id, Merchant.deleted_at.is_(None)).first()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found.")

    m.status = MerchantStatus.APPROVED.value
    m.status_reason = None
    db.commit()
    db.refresh(m)
    return {"data": format_admin_merchant(m)}
