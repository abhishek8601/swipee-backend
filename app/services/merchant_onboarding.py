import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import MerchantStatus
from app.models.merchant import Merchant
from app.models.user import User


def _unique_slug(db: Session, display_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or "merchant"
    slug = base
    suffix = 1
    while db.query(Merchant.id).filter(Merchant.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def ensure_merchant_account(db: Session, user: User) -> Merchant:
    """Link a merchant-role user to a pending merchant profile.

    This also repairs merchant users created before merchant profile onboarding
    was introduced, so they can complete KYC themselves.
    """
    if user.merchant_id and user.merchant:
        return user.merchant
    if not user.phone:
        raise HTTPException(
            status_code=422,
            detail="A phone number is required before creating a merchant profile.",
        )

    merchant = db.query(Merchant).filter(Merchant.email == user.email).first()
    if merchant is None:
        merchant = Merchant(
            legal_name=user.name,
            display_name=user.name,
            slug=_unique_slug(db, user.name),
            email=user.email,
            phone=user.phone,
            status=MerchantStatus.PENDING.value,
        )
        db.add(merchant)
        db.flush()

    user.merchant_id = merchant.id
    user.is_merchant_owner = True
    db.flush()
    return merchant
