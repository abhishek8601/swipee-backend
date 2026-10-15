from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def buyer_payload(**overrides):
    payload = {
        "name": "Jane Buyer",
        "email": "jane@example.com",
        "phone": "+919876543210",
        "password": "secure-password",
        "password_confirmation": "secure-password",
        "gender": "female",
        "terms_accepted": True,
    }
    payload.update(overrides)
    return payload


def test_buyer_registration_creates_buyer_and_returns_token():
    response = client.post("/api/register/user", json=buyer_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Registration successful."
    assert data["token"]
    assert data["user"] == {
        "id": 1,
        "name": "Jane Buyer",
        "email": "jane@example.com",
        "phone": "+919876543210",
        "gender": "female",
        "role": "buyer",
    }

    user = TestingSessionLocal().query(User).filter_by(email="jane@example.com").one()
    assert user.password != "secure-password"
    assert user.role == "buyer"


def test_buyer_registration_rejects_invalid_and_duplicate_values():
    response = client.post("/api/register/user", json=buyer_payload(
        email="not-an-email",
        phone="123",
        password_confirmation="does-not-match",
        terms_accepted=False,
    ))
    assert response.status_code == 422
    assert set(response.json()["errors"]) >= {
        "email", "phone", "password_confirmation", "terms_accepted"
    }

    response = client.post("/api/register/user", json=buyer_payload())
    assert response.status_code == 422
    assert "email" in response.json()["errors"]

    response = client.post("/api/register/user", json=buyer_payload(
        email="another@example.com",
    ))
    assert response.status_code == 422
    assert "phone" in response.json()["errors"]


def test_merchant_registration_creates_linked_pending_profile():
    response = client.post("/api/auth/register", json={
        "name": "Acme Seller",
        "email": "seller@example.com",
        "phone": "+919800000001",
        "password": "secure-password",
        "password_confirmation": "secure-password",
    })

    assert response.status_code == 201
    data = response.json()
    assert data["requires_approval"] is True
    assert "token" not in data
    assert data["user"]["merchant_id"]
    assert data["user"]["merchant"]["status"] == "pending"


def set_merchant_status(email, status, reason=None):
    from app.models.merchant import Merchant
    db = TestingSessionLocal()
    merchant = db.query(Merchant).filter(Merchant.email == email).one()
    merchant.status, merchant.status_reason = status, reason
    db.commit()
    db.close()


def merchant_login(email):
    return client.post("/api/auth/login", json={"email": email, "password": "secure-password"})


def test_merchant_can_log_in_only_after_super_admin_approval():
    email = "approval@example.com"
    assert client.post("/api/auth/register", json={
        "name": "Approval Seller", "email": email, "phone": "+919800000002",
        "password": "secure-password", "password_confirmation": "secure-password",
    }).status_code == 201

    blocked = merchant_login(email)
    assert blocked.status_code == 422
    assert "awaiting approval" in blocked.json()["errors"]["email"][0]

    set_merchant_status(email, "under_review")
    assert merchant_login(email).status_code == 422

    set_merchant_status(email, "approved")
    approved = merchant_login(email)
    assert approved.status_code == 200
    token = approved.json()["token"]
    assert client.get("/api/merchant/profile", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # A token issued while approved stops working once the merchant is suspended.
    set_merchant_status(email, "suspended")
    assert client.get("/api/merchant/profile", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert "suspended" in merchant_login(email).json()["errors"]["email"][0]

    set_merchant_status(email, "rejected", "Incomplete KYC documents")
    message = merchant_login(email).json()["errors"]["email"][0]
    assert "not approved" in message and "Incomplete KYC documents" in message


def test_super_admin_approval_endpoint_unlocks_login():
    from app.core.security import create_access_token
    from app.models.merchant import Merchant
    email = "viaendpoint@example.com"
    assert client.post("/api/auth/register", json={
        "name": "Endpoint Seller", "email": email, "phone": "+919800000003",
        "password": "secure-password", "password_confirmation": "secure-password",
    }).status_code == 201

    db = TestingSessionLocal()
    admin = User(name="Root", email="root@example.com", password="x", phone="+919800000099", role="super_admin", status="active")
    db.add(admin)
    db.commit()
    admin_token = create_access_token({"sub": str(admin.id)})
    merchant_id = db.query(Merchant).filter(Merchant.email == email).one().id
    db.close()

    assert merchant_login(email).status_code == 422
    response = client.post(f"/api/superadmin/merchants/{merchant_id}/approve", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert merchant_login(email).status_code == 200
