from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.inventory import Warehouse

router = APIRouter(prefix="/merchant/warehouses", tags=["merchant-warehouses"])

class WarehouseSchema(BaseModel):
    name: str
    code: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: Optional[str] = "India"
    is_primary: Optional[bool] = False

def format_warehouse(w: Warehouse) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "code": w.code,
        "contact_person": w.contact_person,
        "phone": w.phone,
        "email": w.email,
        "address_line1": w.address_line1,
        "address_line2": w.address_line2,
        "city": w.city,
        "state": w.state,
        "postal_code": w.postal_code,
        "country": w.country,
        "is_primary": bool(w.is_primary),
        "is_active": bool(w.is_active),
    }

@router.get("")
def list_warehouses(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    whs = db.query(Warehouse).filter(
        Warehouse.merchant_id == current_user.merchant_id,
        Warehouse.deleted_at.is_(None)
    ).all()
    return {"data": [format_warehouse(w) for w in whs]}

@router.post("")
def create_warehouse(
    data: WarehouseSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    if data.is_primary:
        db.query(Warehouse).filter(Warehouse.merchant_id == current_user.merchant_id).update({"is_primary": False})

    w = Warehouse(
        merchant_id=current_user.merchant_id,
        **data.model_dump()
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"data": format_warehouse(w)}

@router.get("/{warehouse_id}")
def show_warehouse(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    w = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.merchant_id == current_user.merchant_id,
        Warehouse.deleted_at.is_(None)
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Warehouse not found.")
    return {"data": format_warehouse(w)}

@router.put("/{warehouse_id}")
def update_warehouse(
    warehouse_id: int,
    data: WarehouseSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    w = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.merchant_id == current_user.merchant_id,
        Warehouse.deleted_at.is_(None)
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Warehouse not found.")

    if data.is_primary:
        db.query(Warehouse).filter(Warehouse.merchant_id == current_user.merchant_id).update({"is_primary": False})

    for k, v in data.model_dump().items():
        setattr(w, k, v)

    db.commit()
    db.refresh(w)
    return {"data": format_warehouse(w)}
