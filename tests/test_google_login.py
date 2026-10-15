"""Buyer Google sign-in: token verification and the two-step first sign-up."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.user import User
from app.services import google_auth

CLIENT_ID = "test-web-client.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(key=KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1234567890",
        "email": "maya@gmail.com", "email_verified": True, "name": "Maya Rao",
        "iat": now, "exp": now + 3600, **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture()
def client(monkeypatch):
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
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", f"other-client, {CLIENT_ID}")
    # Google's JWKS is replaced by our key; signature checking itself is real.
    monkeypatch.setattr(google_auth, "_signing_key", lambda token: KEY.public_key())

    db = Session()
    merchant = Merchant(legal_name="M", display_name="M", slug="m", email="seller@gmail.com", phone="9000000000", status="approved")
    db.add(merchant)
    db.flush()
    db.add(User(name="Seller", email="seller@gmail.com", password="x", phone="+919000000001", role="merchant", merchant_id=merchant.id))
    db.add(User(name="Taken", email="taken@gmail.com", password="x", phone="+919000000002", role="buyer"))
    db.commit()
    db.close()

    yield TestClient(app)
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def post(client, **body):
    return client.post("/api/auth/google", json=body)


def test_new_buyer_completes_signup_then_logs_in_again(client):
    first = post(client, id_token=google_token())
    assert first.status_code == 200
    assert first.json()["requires_registration"] is True
    assert first.json()["profile"]["email"] == "maya@gmail.com"
    assert "token" not in first.json()

    created = post(client, id_token=google_token(), phone="+91 98765-11111", terms_accepted=True, gender="female")
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["user"]["role"] == "buyer" and data["user"]["phone"] == "+919876511111"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200

    again = post(client, id_token=google_token())
    assert again.status_code == 200 and again.json()["token"]
    assert again.json()["user"]["id"] == data["user"]["id"]

    # Google-created accounts have no usable password.
    assert client.post("/api/auth/login", json={"email": "maya@gmail.com", "password": ""}).status_code == 422


def test_existing_password_buyer_can_use_google(client):
    resp = post(client, id_token=google_token(email="taken@gmail.com"))
    assert resp.status_code == 200 and resp.json()["user"]["email"] == "taken@gmail.com"


def test_merchant_email_is_refused(client):
    resp = post(client, id_token=google_token(email="seller@gmail.com"))
    assert resp.status_code == 422
    assert "merchant" in resp.json()["errors"]["email"][0]


def test_signup_requires_terms_and_unique_valid_phone(client):
    assert post(client, id_token=google_token(), phone="+919876511111").json()["requires_registration"] is True
    assert post(client, id_token=google_token(), phone="12", terms_accepted=True).status_code == 422
    dup = post(client, id_token=google_token(), phone="+919000000002", terms_accepted=True)
    assert dup.status_code == 422 and "phone" in dup.json()["errors"]


@pytest.mark.parametrize("token, message", [
    (lambda: google_token(aud="someone-elses-app"), "different app"),
    (lambda: google_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200), "expired"),
    (lambda: google_token(iss="https://evil.example.com"), "issuer"),
    (lambda: google_token(email_verified=False), "not verified"),
    (lambda: google_token(key=OTHER_KEY), "Invalid Google sign-in token"),
])
def test_bad_tokens_are_rejected(client, token, message):
    resp = post(client, id_token=token())
    assert resp.status_code == 401
    assert message in resp.json()["message"]


def test_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", "")
    assert post(client, id_token=google_token()).status_code == 503


def test_malformed_token_is_rejected_not_crashed(client, monkeypatch):
    # Real key lookup path (no monkeypatched key): garbage must fail before any network call.
    def real_lookup(token):
        return jwt.PyJWKClient("https://example.invalid/certs").get_signing_key_from_jwt(token)
    monkeypatch.setattr(google_auth, "_signing_key", real_lookup)
    resp = post(client, id_token="aaaaaaaaaaaaaaaaaaaaaaaaa")
    assert resp.status_code == 401
