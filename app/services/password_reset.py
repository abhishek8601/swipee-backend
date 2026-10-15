"""Forgot-password: email a 6-digit code, then set a new password with it.

The code is stored only as an HMAC, expires after PASSWORD_RESET_CODE_TTL_MINUTES,
allows PASSWORD_RESET_MAX_ATTEMPTS wrong guesses, and is single-use. Requesting
a new code retires the previous one.
"""
import hashlib
import hmac
import html as html_lib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.misc import AuditLog, PasswordResetCode
from app.models.user import User
from app.services import mailer

logger = logging.getLogger("swipee.password_reset")


class ResetError(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _hash(user_id: int, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"password-reset:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _find_user(db: Session, email: str) -> Optional[User]:
    user = db.query(User).filter(User.email == email.strip().lower(), User.deleted_at.is_(None)).first()
    return user if user and user.is_active() else None


def create_code(db: Session, email: str, ip: Optional[str]) -> Optional[tuple[User, str]]:
    """Issue a new code, or return None (unknown email, or asked again too soon).

    Callers must answer the client identically either way.
    """
    user = _find_user(db, email)
    if not user:
        return None
    now = datetime.utcnow()
    latest = (
        db.query(PasswordResetCode)
        .filter(PasswordResetCode.user_id == user.id)
        .order_by(PasswordResetCode.created_at.desc())
        .first()
    )
    if latest and latest.created_at > now - timedelta(seconds=settings.PASSWORD_RESET_RESEND_SECONDS):
        return None
    db.query(PasswordResetCode).filter(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None)).update({"used_at": now})
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(PasswordResetCode(
        user_id=user.id,
        code_hash=_hash(user.id, code),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES),
        requested_ip=ip,
        created_at=now,
    ))
    db.add(AuditLog(user_id=user.id, action="auth.password_reset_requested", ip_address=ip, created_at=now))
    db.commit()
    return user, code


def send_code_email(to: str, name: str, code: str) -> None:
    """Background task: a delivery failure is logged, never shown to the requester."""
    minutes = settings.PASSWORD_RESET_CODE_TTL_MINUTES
    text = (
        f"Hi {name},\n\n"
        f"Your Swipee password reset code is: {code}\n\n"
        f"Enter it in the app to choose a new password. The code expires in {minutes} minutes.\n"
        "If you didn't ask to reset your password, you can ignore this email.\n\n"
        "- Team Swipee"
    )
    html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;background:#000;color:#fff;border-radius:12px">
  <h2 style="margin:0 0 16px">swi<span style="color:#ff1f7a">i</span>pe</h2>
  <p>Hi {html_lib.escape(name)},</p>
  <p>Your password reset code is:</p>
  <p style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#ff1f7a;margin:16px 0">{code}</p>
  <p>Enter it in the app to choose a new password. It expires in {minutes} minutes.</p>
  <p style="color:#a3a3ad;font-size:13px">If you didn't ask to reset your password, you can ignore this email.</p>
</div>"""
    try:
        mailer.send_email(to, "Your Swipee password reset code", text, html)
    except mailer.MailError as e:
        logger.error("Password reset email to %s failed: %s", to, e)


def reset_password(db: Session, email: str, code: str, new_password: str, ip: Optional[str]) -> User:
    invalid = ResetError("code", "This code is invalid or has expired. Request a new one.")
    user = _find_user(db, email)
    if not user:
        raise invalid
    now = datetime.utcnow()
    row = (
        db.query(PasswordResetCode)
        .filter(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None))
        .order_by(PasswordResetCode.created_at.desc())
        .first()
    )
    if not row or row.expires_at < now or row.attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
        raise invalid
    if not hmac.compare_digest(row.code_hash, _hash(user.id, code.strip())):
        row.attempts += 1
        left = settings.PASSWORD_RESET_MAX_ATTEMPTS - row.attempts
        db.commit()
        if left <= 0:
            raise ResetError("code", "Too many wrong attempts. Request a new code.")
        raise ResetError("code", f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left.")

    user.password = get_password_hash(new_password)
    row.used_at = now
    db.add(AuditLog(user_id=user.id, action="auth.password_reset", ip_address=ip, created_at=now))
    db.commit()
    return user
