import re
from typing import Optional

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


AWAITING_APPROVAL_MESSAGE = (
    "Your merchant account is awaiting approval by the Swipee team. "
    "You can log in once a super admin approves it."
)


def merchant_access_block_reason(user: User) -> Optional[str]:
    """Why a merchant-side user may not sign in or use the API, or None if they may.

    Merchant owners and staff get access only once a super admin has approved
    the merchant account; until then (and after rejection or suspension) the
    account is locked out.
    """
    if not user.is_merchant_side:
        return None
    merchant = user.merchant
    if merchant is None or merchant.deleted_at is not None:
        return AWAITING_APPROVAL_MESSAGE if merchant is None else "This merchant account no longer exists. Contact support."
    status = merchant.status
    if status == MerchantStatus.APPROVED.value:
        return None
    if status == MerchantStatus.SUSPENDED.value:
        return "Your merchant account is suspended. Contact support."
    if status == MerchantStatus.REJECTED.value:
        reason = f" Reason: {merchant.status_reason}" if merchant.status_reason else ""
        return f"Your merchant application was not approved.{reason} Contact support for help."
    return AWAITING_APPROVAL_MESSAGE  # pending, under_review


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
