from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.misc import AuditLog
from app.schemas.auth import (
    LoginRequest, LoginResponse, MeResponse, UserResponse, MerchantSnippet, ChangePasswordRequest,
    RegisterRequest
)
from app.core.enums import MerchantStatus, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])

def format_user_response(user: User) -> UserResponse:
    merchant_data = None
    if user.merchant:
        merchant_data = MerchantSnippet(
            id=user.merchant.id,
            display_name=user.merchant.display_name,
            slug=user.merchant.slug,
            status=user.merchant.status,
            status_label=user.merchant.status_label,
            can_trade=user.merchant.can_trade,
            logo_url=f"/storage/{user.merchant.logo_path}" if user.merchant.logo_path else None
        )

    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        avatar_url=f"/storage/{user.avatar_path}" if user.avatar_path else None,
        role=user.role,
        role_label=user.get_role_label(),
        status=user.status,
        merchant_id=user.merchant_id,
        is_merchant_owner=bool(user.is_merchant_owner),
        must_change_password=bool(user.must_change_password),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        merchant=merchant_data,
        created_at=user.created_at.isoformat() if user.created_at else None
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a standard merchant user account and immediately issue a JWT."""
    email = str(body.email).lower()
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["An account with this email already exists."]}}
        )

    user = User(
        name=body.name.strip(),
        email=email,
        password=get_password_hash(body.password),
        phone=body.phone.strip() if body.phone else None,
        role=UserRole.MERCHANT.value,
        status="active",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["An account with this email already exists."]}}
        )
    db.refresh(user)

    user.last_login_at = datetime.utcnow()
    user.last_login_ip = request.client.host if request.client else None
    db.add(AuditLog(
        user_id=user.id,
        action="auth.register",
        ip_address=user.last_login_ip,
        created_at=datetime.utcnow(),
    ))
    db.commit()

    return LoginResponse(
        token=create_access_token(data={"sub": str(user.id), "role": user.role}),
        user=format_user_response(user),
        must_change_password=False,
    )


@router.post("/login", response_model=LoginResponse)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower(), User.deleted_at.is_(None)).first()

    if not user or not verify_password(body.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["These credentials do not match our records."]}}
        )

    if not user.is_active():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["This account has been deactivated. Contact your administrator."]}}
        )

    if user.is_merchant_side and user.merchant and user.merchant.status == MerchantStatus.SUSPENDED.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["Your merchant account is suspended. Contact support."]}}
        )

    # Issue token
    token = create_access_token(data={"sub": str(user.id), "role": user.role})

    user.last_login_at = datetime.utcnow()
    user.last_login_ip = request.client.host if request.client else None
    db.commit()

    # Log audit
    audit = AuditLog(
        user_id=user.id,
        action="auth.login",
        ip_address=user.last_login_ip,
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    return LoginResponse(
        token=token,
        user=format_user_response(user),
        must_change_password=bool(user.must_change_password)
    )

@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    return MeResponse(
        user=format_user_response(current_user),
        permissions=current_user.get_all_permissions(),
        role=current_user.role
    )

@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Logged out successfully."}

@router.post("/logout-all")
def logout_all(current_user: User = Depends(get_current_user)):
    return {"message": "Logged out from all devices."}

@router.post("/change-password")
def change_password(body: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, current_user.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"current_password": ["The provided password does not match our records."]}}
        )
    if body.password != body.password_confirmation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"password_confirmation": ["The password confirmation does not match."]}}
        )

    current_user.password = get_password_hash(body.password)
    current_user.must_change_password = False
    db.commit()

    return {"message": "Password updated successfully."}
