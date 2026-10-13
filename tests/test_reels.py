"""Merchant reel workflow: personas -> generate -> store -> publish -> buyer feed.

External services are replaced at their network boundary only: the video
provider's start/poll, the provider download, and the Drive upload. Everything
else (validation, ownership, leases, status tracks, feed rules) runs for real.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.ai_model import AiModel, ProductTryOn
from app.models.merchant import Merchant
from app.models.product import Product, ProductImage
from app.models.taxonomy import Brand, Category
from app.models.user import User
from app.services import drive_storage, reel_service, video_provider
from app.services.ai_model_roster import ensure_default_ai_models
from app.services.tryon_service import TryOnService

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64

TestingSessionLocal = None  # fresh in-memory database per test, see `env`


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class FakeProvider:
    name = "fake"
    starts = 0
    outcome = "succeeded"

    def missing_configuration(self):
        return []

    async def start(self, keyframe_path, prompt, duration):
        assert keyframe_path.is_file()
        FakeProvider.starts += 1
        return f"job-{FakeProvider.starts}"

    async def poll(self, job_id):
        if FakeProvider.outcome == "failed":
            return video_provider.JobState("failed", error="content policy")
        return video_provider.JobState("succeeded", output_url="https://provider.example/out.mp4")


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 80), (120, 30, 60)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    global TestingSessionLocal
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path / "public")
    monkeypatch.setattr(settings, "PRIVATE_STORAGE_DIR", tmp_path / "private")
    (tmp_path / "public" / "products").mkdir(parents=True)
    monkeypatch.setattr(settings, "TRYON_ALLOW_PLACEHOLDER_PUBLISH", True)
    monkeypatch.setattr(reel_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(reel_service, "POLL_INTERVAL_SECONDS", 0)

    FakeProvider.starts, FakeProvider.outcome = 0, "succeeded"
    monkeypatch.setattr(video_provider, "get_provider", lambda: FakeProvider())

    async def fake_still(inputs, scene="studio"):
        path = settings.STORAGE_DIR / "try-ons" / f"k_{inputs['try_on_id']}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg_bytes())
        return {"path": f"try-ons/{path.name}", "provider": "stub", "is_placeholder": True, "prompt": "p"}
    monkeypatch.setattr(TryOnService, "render_still", staticmethod(fake_still))

    async def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(MP4_BYTES)
        return len(MP4_BYTES)
    monkeypatch.setattr(reel_service, "_download_video", fake_download)

    uploads = []
    async def fake_upload(path, name, props):
        uploads.append(props)
        return {"id": f"drive-{props['reel_id']}", "size": str(path.stat().st_size)}
    monkeypatch.setattr(drive_storage, "upload_video", fake_upload)
    monkeypatch.setattr(drive_storage, "is_configured", lambda: True)

    db = TestingSessionLocal()
    ensure_default_ai_models(db)
    brand = Brand(name="B", slug="b", status="approved", is_active=True)
    cat = Category(name="C", slug="c", is_active=True)
    db.add_all([brand, cat])
    db.flush()

    def merchant(slug, status="approved"):
        m = Merchant(legal_name=slug, display_name=slug.title(), slug=slug, email=f"{slug}@x.test", phone="9999999999", status=status)
        db.add(m)
        db.flush()
        u = User(name=slug, email=f"owner@{slug}.test", password="x", phone=f"9{m.id:09d}", role="merchant", merchant_id=m.id, is_merchant_owner=True)
        db.add(u)
        db.flush()
        p = Product(merchant_id=m.id, brand_id=brand.id, category_id=cat.id, name=f"{slug} kurta", slug=f"{slug}-kurta", style_code="S1", mrp=2000, selling_price=1500, status="approved", is_active=True)
        db.add(p)
        db.flush()
        img_dir = settings.STORAGE_DIR / "products" / str(p.id)
        img_dir.mkdir(parents=True)
        (img_dir / "front.jpg").write_bytes(jpeg_bytes())
        db.add(ProductImage(product_id=p.id, image_path=f"products/{p.id}/front.jpg", is_primary=True))
        return {"merchant_id": m.id, "product_id": p.id, "headers": {"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"}}

    a, b = merchant("alpha"), merchant("beta")
    db.commit()
    model_id = db.query(AiModel).filter_by(slug="kavya").one().id
    db.close()

    yield {"client": TestClient(app), "a": a, "b": b, "model_id": model_id, "uploads": uploads}

    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def generate(env, who="a", **body):
    payload = {"ai_model_id": env["model_id"], "scene_style": "studio", "duration_seconds": 20, **body}
    return env["client"].post(f"/api/merchant/products/{env[who]['product_id']}/reels", json=payload, headers=env[who]["headers"])


def test_merchant_sees_five_personas_and_provisioning_is_idempotent(env):
    resp = env["client"].get("/api/merchant/ai-models", headers=env["a"]["headers"])
    assert resp.status_code == 200
    models = resp.json()["data"]
    assert [m["slug"] for m in models] == ["arjun", "meera", "kabir", "ananya", "kavya"]
    assert all(m["is_available"] and m["persona_id"] for m in models)
    assert len({m["id"] for m in models}) == 5

    db = TestingSessionLocal()
    assert ensure_default_ai_models(db) == []
    assert db.query(AiModel).count() == 5
    db.close()


def test_full_workflow_generate_store_publish_feed(env):
    c = env["client"]
    resp = generate(env)
    assert resp.status_code == 202, resp.text
    reel_id = resp.json()["data"]["id"]

    # TestClient runs background tasks before returning: the pipeline has finished.
    reel = c.get(f"/api/merchant/reels/{reel_id}", headers=env["a"]["headers"]).json()["data"]
    assert reel["status"] == "completed"
    assert reel["media_type"] == "video"
    assert reel["product"]["id"] == env["a"]["product_id"]
    assert reel["ai_model_id"] == env["model_id"]
    assert reel["source_image_url"].endswith("front.jpg")
    assert reel["storage_status"] == "uploaded" and reel["storage_file_id"] == f"drive-{reel_id}"
    assert env["uploads"][0] == {"reel_id": reel_id, "merchant_id": env["a"]["merchant_id"], "product_id": env["a"]["product_id"], "ai_model_id": env["model_id"]}
    assert reel["is_published"] is False and reel["can_publish"] is True

    # Owner preview through the signed URL; unsigned access to an unpublished reel is refused.
    assert c.get(reel["video_url"]).content == MP4_BYTES
    assert c.get(f"/api/reels/{reel_id}/video").status_code == 404
    assert c.get("/api/feed/reels").json()["data"] == []

    assert c.post(f"/api/merchant/reels/{reel_id}/publish", headers=env["a"]["headers"]).status_code == 200
    feed = c.get("/api/feed/reels").json()["data"]
    assert [r["id"] for r in feed] == [reel_id]
    assert feed[0]["product"]["id"] == env["a"]["product_id"] and feed[0]["product"]["price"] == 1500.0
    assert c.get(feed[0]["video_url"]).content == MP4_BYTES

    assert c.post(f"/api/merchant/reels/{reel_id}/unpublish", headers=env["a"]["headers"]).status_code == 200
    assert c.get("/api/feed/reels").json()["data"] == []


def test_other_merchant_cannot_see_or_act_on_reel(env):
    reel_id = generate(env).json()["data"]["id"]
    c, hb = env["client"], env["b"]["headers"]
    assert c.get(f"/api/merchant/reels/{reel_id}", headers=hb).status_code == 404
    assert c.post(f"/api/merchant/reels/{reel_id}/publish", headers=hb).status_code == 404
    assert c.delete(f"/api/merchant/try-ons/{reel_id}", headers=hb).status_code == 404
    assert c.get("/api/merchant/reels", headers=hb).json()["data"] == []
    # Merchant B cannot generate against merchant A's product either.
    resp = c.post(f"/api/merchant/products/{env['a']['product_id']}/reels", json={"ai_model_id": env["model_id"]}, headers=hb)
    assert resp.status_code == 404


def test_idempotency_key_prevents_duplicate_reels(env):
    key = {"Idempotency-Key": "reel-req-0001"}
    first = env["client"].post(f"/api/merchant/products/{env['a']['product_id']}/reels", json={"ai_model_id": env["model_id"]}, headers={**env["a"]["headers"], **key})
    second = env["client"].post(f"/api/merchant/products/{env['a']['product_id']}/reels", json={"ai_model_id": env["model_id"]}, headers={**env["a"]["headers"], **key})
    assert first.status_code == 202 and second.status_code == 200
    assert second.json()["deduplicated"] is True
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    db = TestingSessionLocal()
    assert db.query(ProductTryOn).count() == 1
    db.close()
    assert FakeProvider.starts == 1


def test_failed_generation_retry_starts_new_job_and_reuses_row(env):
    FakeProvider.outcome = "failed"
    reel_id = generate(env).json()["data"]["id"]
    c, h = env["client"], env["a"]["headers"]
    reel = c.get(f"/api/merchant/reels/{reel_id}", headers=h).json()["data"]
    assert reel["status"] == "failed" and "content policy" in reel["error_message"]
    assert c.post(f"/api/merchant/reels/{reel_id}/publish", headers=h).status_code == 422

    FakeProvider.outcome = "succeeded"
    assert c.post(f"/api/merchant/reels/{reel_id}/retry", headers=h).status_code == 200
    reel = c.get(f"/api/merchant/reels/{reel_id}", headers=h).json()["data"]
    assert reel["status"] == "completed" and reel["generation_attempts"] == 2
    # Retrying a non-failed reel is refused rather than starting a second job.
    assert c.post(f"/api/merchant/reels/{reel_id}/retry", headers=h).status_code == 409
    db = TestingSessionLocal()
    assert db.query(ProductTryOn).count() == 1
    db.close()


def test_storage_failure_is_tracked_separately_and_retryable(env, monkeypatch):
    async def broken_upload(path, name, props):
        raise drive_storage.DriveError("quota exceeded", retryable=True)
    good_upload = drive_storage.upload_video
    monkeypatch.setattr(drive_storage, "upload_video", broken_upload)

    reel_id = generate(env).json()["data"]["id"]
    c, h = env["client"], env["a"]["headers"]
    reel = c.get(f"/api/merchant/reels/{reel_id}", headers=h).json()["data"]
    assert reel["status"] == "completed"
    assert reel["storage_status"] == "failed" and "quota" in reel["storage_error"]

    monkeypatch.setattr(drive_storage, "upload_video", good_upload)
    assert c.post(f"/api/merchant/reels/{reel_id}/retry-upload", headers=h).status_code == 200
    reel = c.get(f"/api/merchant/reels/{reel_id}", headers=h).json()["data"]
    assert reel["storage_status"] == "uploaded"
    assert FakeProvider.starts == 1  # the video was not regenerated


def test_drive_not_configured_is_reported_not_faked(env, monkeypatch):
    monkeypatch.setattr(drive_storage, "is_configured", lambda: False)
    reel_id = generate(env).json()["data"]["id"]
    reel = env["client"].get(f"/api/merchant/reels/{reel_id}", headers=env["a"]["headers"]).json()["data"]
    assert reel["storage_status"] == "not_configured"
    assert "GOOGLE_DRIVE_FOLDER_ID" in reel["storage_error"]


def test_generation_refused_when_provider_not_configured(env, monkeypatch):
    monkeypatch.setattr(video_provider, "get_provider", lambda: None)
    resp = generate(env)
    assert resp.status_code == 503
    assert any("VIDEO_PROVIDER" in m for m in resp.json()["missing_configuration"])
    db = TestingSessionLocal()
    assert db.query(ProductTryOn).count() == 0
    db.close()


def test_validation_errors(env):
    assert generate(env, ai_model_id=99999).status_code == 422
    assert generate(env, duration_seconds=5).status_code == 422
    assert generate(env, scene_style="moon").status_code == 422
    assert generate(env, source_image_id=99999).status_code == 422


def test_placeholder_moderation_and_product_rules_gate_the_feed(env, monkeypatch):
    c, h = env["client"], env["a"]["headers"]
    reel_id = generate(env).json()["data"]["id"]

    monkeypatch.setattr(settings, "TRYON_ALLOW_PLACEHOLDER_PUBLISH", False)
    resp = c.post(f"/api/merchant/reels/{reel_id}/publish", headers=h)
    assert resp.status_code == 422 and "placeholder" in resp.json()["message"]
    monkeypatch.setattr(settings, "TRYON_ALLOW_PLACEHOLDER_PUBLISH", True)
    assert c.post(f"/api/merchant/reels/{reel_id}/publish", headers=h).status_code == 200

    db = TestingSessionLocal()
    product = db.get(Product, env["a"]["product_id"])
    product.is_active = False
    db.commit()
    assert c.get("/api/feed/reels").json()["data"] == []
    product.is_active = True
    reel = db.get(ProductTryOn, reel_id)
    reel.moderation_status = "disabled"
    reel.is_published = False
    db.commit()
    db.close()
    assert c.get("/api/feed/reels").json()["data"] == []
    resp = c.post(f"/api/merchant/reels/{reel_id}/publish", headers=h)
    assert resp.status_code == 422 and "moderation" in resp.json()["message"]


def test_product_image_upload_validates_content(env):
    c, h, pid = env["client"], env["a"]["headers"], env["a"]["product_id"]
    bad = c.post(f"/api/merchant/products/{pid}/images", files={"image": ("x.jpg", b"not an image", "image/jpeg")}, headers=h)
    assert bad.status_code == 422
    good = c.post(f"/api/merchant/products/{pid}/images", files={"image": ("../../evil name.jpg", jpeg_bytes(), "image/jpeg")}, headers=h)
    assert good.status_code == 200
    url = good.json()["data"]["image_url"]
    assert ".." not in url and url.startswith(f"/storage/products/{pid}/")
