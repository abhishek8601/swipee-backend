from typing import Optional, List, Callable
from fastapi import Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.merchant import Merchant
from app.core.enums import UserRole, MerchantStatus

def get_token_from_header(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthenticated."
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization token."
        )
    return parts[1]

def get_current_user(
    token: str = Depends(get_token_from_header),
    db: Session = Depends(get_db)
) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthenticated."
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthenticated."
        )
    user = db.query(User).filter(User.id == int(user_id), User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found."
        )
    if not user.is_active():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact your administrator."
        )
    if user.is_merchant_side and user.merchant:
        if user.merchant.status == MerchantStatus.SUSPENDED.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your merchant account is suspended. Contact support."
            )
    return user

def require_roles(*allowed_roles: str) -> Callable:
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.is_super_admin:
            return user
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action is unauthorized."
            )
        return user
    return role_checker

def require_permissions(*required_perms: str) -> Callable:
    def perm_checker(user: User = Depends(get_current_user)) -> User:
        if user.is_super_admin:
            return user
        for perm in required_perms:
            if not user.has_permission(perm):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"This action is unauthorized. Missing permission: {perm}"
                )
        return user
    return perm_checker

def require_merchant_can_trade(user: User = Depends(get_current_user)) -> User:
    """Equivalent to Laravel's merchant.trading middleware: gates writes when merchant cannot trade."""
    if user.is_platform_side:
        return user
    if not user.merchant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No merchant associated with this account."
        )
    if not user.merchant.can_trade:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Merchant account cannot trade (current status: {user.merchant.status_label})."
        )
    return user

def get_current_merchant(user: User = Depends(get_current_user)) -> Merchant:
    if not user.merchant_id or not user.merchant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with a merchant."
        )
    return user.merchant
