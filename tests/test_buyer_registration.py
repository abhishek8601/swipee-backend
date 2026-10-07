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
    assert data["user"]["merchant_id"]
    assert data["user"]["merchant"]["status"] == "pending"

    response = client.get("/api/merchant/profile", headers={"Authorization": f"Bearer {data['token']}"})
    assert response.status_code == 200
