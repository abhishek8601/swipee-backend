"""Forgot password: emailed 6-digit code, then a new password."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.main import app
from app.models.misc import PasswordResetCode
from app.models.user import User
from app.services import mailer

EMAIL = "riya@example.com"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: sent.append({"to": to, "text": text, "html": html}))

    db = Session()
    db.add(User(name="Riya <b>", email=EMAIL, password=get_password_hash("old-password"), phone="+919811111111", role="buyer"))
    db.commit()
    db.close()

    yield {"client": TestClient(app), "sent": sent, "Session": Session}
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def forgot(env, email=EMAIL):
    return env["client"].post("/api/auth/forgot-password", json={"email": email})


def reset(env, code, password="new-password-1", confirm=None):
    return env["client"].post("/api/auth/reset-password", json={
        "email": EMAIL, "code": code, "password": password, "password_confirmation": confirm or password,
    })


def code_from(mail) -> str:
    return re.search(r"\b(\d{6})\b", mail["text"]).group(1)


def login(env, password):
    return env["client"].post("/api/auth/login", json={"email": EMAIL, "password": password})


def age_codes(env, seconds):
    db = env["Session"]()
    for row in db.query(PasswordResetCode).all():
        row.created_at -= timedelta(seconds=seconds)
    db.commit()
    db.close()


def test_full_reset_flow(env):
    resp = forgot(env)
    assert resp.status_code == 200
    assert len(env["sent"]) == 1 and env["sent"][0]["to"] == EMAIL
    assert "&lt;b&gt;" in env["sent"][0]["html"]  # user name is HTML-escaped
    code = code_from(env["sent"][0])

    assert reset(env, code).status_code == 200
    assert login(env, "new-password-1").status_code == 200
    assert login(env, "old-password").status_code == 422
    # Single use.
    assert reset(env, code, "another-pass-2").status_code == 422


def test_unknown_email_gets_identical_reply_and_no_mail(env):
    known = forgot(env).json()
    unknown = forgot(env, "nobody@example.com").json()
    assert known == unknown
    assert len(env["sent"]) == 1


def test_wrong_code_counts_attempts_then_locks(env):
    forgot(env)
    code = code_from(env["sent"][0])
    wrong = "000000" if code != "000000" else "111111"
    first = reset(env, wrong)
    assert first.status_code == 422 and "4 attempts left" in first.json()["errors"]["code"][0]
    for _ in range(settings.PASSWORD_RESET_MAX_ATTEMPTS - 1):
        reset(env, wrong)
    # Even the right code is refused once the attempts are used up.
    assert reset(env, code).status_code == 422
    assert login(env, "old-password").status_code == 200


def test_expired_code_is_refused(env):
    forgot(env)
    code = code_from(env["sent"][0])
    db = env["Session"]()
    row = db.query(PasswordResetCode).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert reset(env, code).status_code == 422


def test_resend_is_throttled_and_new_code_replaces_old(env):
    forgot(env)
    forgot(env)
    assert len(env["sent"]) == 1  # second request inside the resend window: no new mail
    old_code = code_from(env["sent"][0])

    age_codes(env, settings.PASSWORD_RESET_RESEND_SECONDS + 1)
    forgot(env)
    assert len(env["sent"]) == 2
    new_code = code_from(env["sent"][1])
    if new_code != old_code:
        assert reset(env, old_code).status_code == 422
    assert reset(env, new_code).status_code == 200


def test_password_rules(env):
    forgot(env)
    code = code_from(env["sent"][0])
    assert reset(env, code, "short").status_code == 422
    assert reset(env, code, "new-password-1", "different-pass").status_code == 422
    assert env["client"].post("/api/auth/reset-password", json={"email": EMAIL, "code": "12ab", "password": "new-password-1", "password_confirmation": "new-password-1"}).status_code == 422


def test_mail_failure_is_not_exposed(env, monkeypatch):
    def boom(*a, **k):
        raise mailer.MailError("smtp down")
    monkeypatch.setattr(mailer, "send_email", boom)
    resp = forgot(env)
    assert resp.status_code == 200 and "smtp" not in resp.text.lower()


def test_reserved_domain_emails_like_demo_accounts_work(env):
    db = env["Session"]()
    db.add(User(name="Demo", email="buyer@swipee.test", password=get_password_hash("password"), phone="+919822222222", role="buyer"))
    db.commit()
    db.close()
    assert forgot(env, "buyer@swipee.test").status_code == 200
    assert env["sent"][-1]["to"] == "buyer@swipee.test"
    assert forgot(env, "not-an-email").status_code == 422
