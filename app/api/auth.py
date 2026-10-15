import secrets
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.misc import AuditLog
from app.services import google_auth, password_reset
from app.services.merchant_onboarding import ensure_merchant_account, merchant_access_block_reason
from app.schemas.auth import (
    LoginRequest, LoginResponse, MeResponse, UserResponse, MerchantSnippet, ChangePasswordRequest,
    RegisterRequest, BuyerRegisterRequest, BuyerRegisterResponse, BuyerUserResponse, MerchantRegisterResponse, GoogleLoginRequest,
    ForgotPasswordRequest, ResetPasswordRequest
)
from app.core.enums import MerchantStatus, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])
public_router = APIRouter(tags=["auth"])

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


@public_router.post("/register/user", response_model=BuyerRegisterResponse, status_code=status.HTTP_201_CREATED)
def register_buyer(request: Request, body: BuyerRegisterRequest, db: Session = Depends(get_db)):
    """Register a buyer/customer account and issue an authentication token."""
    email = str(body.email).lower()
    phone = body.normalized_phone

    duplicate_email = db.query(User.id).filter(User.email == email).first()
    if duplicate_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "The given data was invalid.", "errors": {"email": ["An account with this email already exists."]}},
        )

    duplicate_phone = db.query(User.id).filter(User.phone == phone).first()
    if duplicate_phone:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "The given data was invalid.", "errors": {"phone": ["An account with this phone number already exists."]}},
        )

    user = User(
        name=body.name.strip(),
        email=email,
        phone=phone,
        password=get_password_hash(body.password),
        gender=body.gender,
        role=UserRole.BUYER.value,
        status="active",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        error_text = str(getattr(exc, "orig", exc)).lower()
        field = "phone" if "phone" in error_text else "email"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The given data was invalid.",
                "errors": {field: [f"An account with this {('phone number' if field == 'phone' else 'email')} already exists."]},
            },
        )
    db.refresh(user)

    user.last_login_at = datetime.utcnow()
    user.last_login_ip = request.client.host if request.client else None
    db.add(AuditLog(
        user_id=user.id,
        action="auth.buyer_registered",
        ip_address=user.last_login_ip,
        created_at=datetime.utcnow(),
    ))
    db.commit()

    return BuyerRegisterResponse(
        message="Registration successful.",
        user=BuyerUserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            gender=user.gender,
            role=user.role,
        ),
        token=create_access_token(data={"sub": str(user.id), "role": user.role}),
    )


@router.post("/register", response_model=MerchantRegisterResponse, status_code=status.HTTP_201_CREATED)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a merchant account in "pending" status.

    No token is issued: the merchant can log in only after a super admin
    approves the account (POST /superadmin/merchants/{id}/approve).
    """
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
        db.flush()
        ensure_merchant_account(db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": ["An account or merchant with this email already exists."]}}
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

    return MerchantRegisterResponse(
        message="Registration submitted. You can log in once a super admin approves your merchant account.",
        user=format_user_response(user),
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

    if user.role == UserRole.MERCHANT.value and not user.merchant_id and user.phone:
        # Older merchant users with no merchant profile: create the pending
        # profile now so it shows up in the super admin approval queue.
        ensure_merchant_account(db, user)
        db.commit()
        db.refresh(user)

    blocked = merchant_access_block_reason(user)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": {"email": [blocked]}}
        )

    # Issue token
    token = create_access_token(data={"sub": str(user.id), "role": user.role})

    user.last_login_at = datetime.utcnow()
    user.last_login_ip = request.client.host if request.client else None
    db.commit()

    # Log audit
    audit = AuditLog(
        user_id=user.id,
        action="superadmin.login" if user.role == UserRole.SUPER_ADMIN.value else "auth.login",
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

@router.post("/google")
def google_login(request: Request, body: GoogleLoginRequest, db: Session = Depends(get_db)):
    """Buyer sign-in with a Google ID token.

    - Existing buyer with the token's (verified) email: logged in.
    - Merchant/admin email: refused; those accounts use email + password.
    - New email: responds `requires_registration` until the app resends the
      token with `phone` and `terms_accepted` (every account needs a unique
      phone number), then creates the buyer and logs them in.
    """
    if not google_auth.is_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this server (set GOOGLE_OAUTH_CLIENT_IDS).")
    try:
        claims = google_auth.verify_id_token(body.id_token)
    except google_auth.GoogleTokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    email = claims["email"].lower()
    ip = request.client.host if request.client else None
    user = db.query(User).filter(User.email == email).first()

    if user:
        if user.deleted_at is not None or not user.is_active():
            raise HTTPException(status_code=422, detail={"errors": {"email": ["This account has been deactivated. Contact support."]}})
        if not user.is_customer:
            raise HTTPException(status_code=422, detail={"errors": {"email": [
                "Google sign-in is for shoppers. This email belongs to a merchant or staff account; log in with your email and password."
            ]}})
        user.last_login_at, user.last_login_ip = datetime.utcnow(), ip
        db.add(AuditLog(user_id=user.id, action="auth.google_login", ip_address=ip, created_at=datetime.utcnow()))
        db.commit()
        db.refresh(user)
        return {
            "success": True,
            "message": "Logged in with Google.",
            "token": create_access_token(data={"sub": str(user.id), "role": user.role}),
            "user": format_user_response(user).model_dump(),
        }

    profile = {"name": claims.get("name") or email.split("@")[0], "email": email, "picture": claims.get("picture")}
    if not body.phone or not body.terms_accepted:
        return {
            "success": True,
            "requires_registration": True,
            "message": "Add your phone number and accept the terms to finish creating your account.",
            "profile": profile,
        }

    if db.query(User.id).filter(User.phone == body.phone).first():
        raise HTTPException(status_code=422, detail={"message": "The given data was invalid.", "errors": {"phone": ["An account with this phone number already exists."]}})

    user = User(
        name=profile["name"][:255],
        email=email,
        phone=body.phone,
        # Google-only account: random password nobody knows, so password login stays closed.
        password=get_password_hash(secrets.token_urlsafe(32)),
        gender=body.gender,
        role=UserRole.BUYER.value,
        status="active",
        email_verified_at=datetime.utcnow(),
        last_login_at=datetime.utcnow(),
        last_login_ip=ip,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=422, detail={"message": "The given data was invalid.", "errors": {"phone": ["An account with this phone number or email already exists."]}})
    db.refresh(user)
    db.add(AuditLog(user_id=user.id, action="auth.google_registered", ip_address=ip, created_at=datetime.utcnow()))
    db.commit()
    return JSONResponse(status_code=201, content={
        "success": True,
        "message": "Account created with Google.",
        "token": create_access_token(data={"sub": str(user.id), "role": user.role}),
        "user": format_user_response(user).model_dump(),
    })


FORGOT_PASSWORD_MESSAGE = "If an account exists for that email, we've sent a 6-digit reset code. It expires in {minutes} minutes."


@router.post("/forgot-password")
def forgot_password(request: Request, body: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Email a reset code. The reply never reveals whether the email is registered,
    and sending happens in the background so response time doesn't either."""
    issued = password_reset.create_code(db, str(body.email), request.client.host if request.client else None)
    if issued:
        user, code = issued
        background_tasks.add_task(password_reset.send_code_email, user.email, user.name, code)
    return {"success": True, "message": FORGOT_PASSWORD_MESSAGE.format(minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES)}


@router.post("/reset-password")
def reset_password(request: Request, body: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        password_reset.reset_password(db, str(body.email), body.code, body.password, request.client.host if request.client else None)
    except password_reset.ResetError as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "errors": {e.field: [str(e)]}})
    return {"success": True, "message": "Your password has been updated. You can now log in."}


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    return MeResponse(
        user=format_user_response(current_user),
        permissions=current_user.get_all_permissions(),
        role=current_user.role
    )

@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.SUPER_ADMIN.value:
        db.add(AuditLog(
            user_id=current_user.id,
            action="superadmin.logout",
            ip_address=request.client.host if request.client else None,
            created_at=datetime.utcnow(),
        ))
        db.commit()
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
