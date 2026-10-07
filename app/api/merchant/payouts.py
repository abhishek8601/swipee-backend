from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_merchant
from app.models.merchant import Merchant
from app.models.misc import Payout

router = APIRouter(prefix="/merchant/payouts", tags=["merchant-payouts"])


def format_payout(payout: Payout) -> dict:
    return {
        "id": payout.id, "payout_number": payout.payout_number,
        "period_start": payout.period_start.isoformat(), "period_end": payout.period_end.isoformat(),
        "gross_sales": float(payout.gross_sales or 0), "commission_total": float(payout.commission_total or 0),
        "tax_total": float(payout.tax_total or 0), "net_payout": float(payout.net_payout or 0),
        "status": payout.status, "processed_at": payout.processed_at.isoformat() if payout.processed_at else None,
    }


@router.get("")
def list_payouts(db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    payouts = db.query(Payout).filter(Payout.merchant_id == merchant.id).order_by(Payout.period_end.desc()).all()
    return {"data": [format_payout(payout) for payout in payouts]}


@router.get("/{payout_id}")
def get_payout(payout_id: int, db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    payout = db.query(Payout).filter(Payout.id == payout_id, Payout.merchant_id == merchant.id).first()
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found.")
    return {"data": format_payout(payout)}
