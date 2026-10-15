"""Super admin imports Google Drive videos as product reels; all feeds show them."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.ai_model import ProductTryOn
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.taxonomy import Brand, Category
from app.models.user import User
from app.services import drive_storage

FOLDER = "reels-folder-123"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
DRIVE = {
    "vid-1": {"id": "vid-1", "name": "kurta-walk.mp4", "mimeType": "video/mp4", "size": "2048", "parents": [FOLDER],
              "videoMediaMetadata": {"width": 1080, "height": 1920, "durationMillis": "18500"}, "hasThumbnail": True},
    "vid-2": {"id": "vid-2", "name": "tee-spin.mov", "mimeType": "video/quicktime", "parents": [FOLDER], "videoMediaMetadata": {}},
    "elsewhere": {"id": "elsewhere", "name": "private.mp4", "mimeType": "video/mp4", "parents": ["some-other-folder"]},
}


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

    deleted = []
    async def list_videos(folder_id):
        return [f for f in DRIVE.values() if folder_id in f["parents"]]
    async def get_file(file_id):
        return DRIVE.get(file_id)
    async def stream(file_id, range_header):
        async def body():
            yield MP4
        return 200, {"content-length": str(len(MP4))}, body()
    async def delete(file_id):
        deleted.append(file_id)
    monkeypatch.setattr(drive_storage, "can_read", lambda: True)
    monkeypatch.setattr(drive_storage, "is_configured", lambda: True)
    monkeypatch.setattr(drive_storage, "reels_folder_id", lambda: FOLDER)
    monkeypatch.setattr(drive_storage, "list_folder_videos", list_videos)
    monkeypatch.setattr(drive_storage, "get_file", get_file)
    monkeypatch.setattr(drive_storage, "stream_file", stream)
    monkeypatch.setattr(drive_storage, "delete_file", delete)

    db = Session()
    brand, cat = Brand(name="B", slug="b", status="approved", is_active=True), Category(name="C", slug="c", is_active=True)
    merchant = Merchant(legal_name="Shop", display_name="Shop", slug="shop", email="shop@x.test", phone="9000000000", status="approved")
    db.add_all([brand, cat, merchant])
    db.flush()
    live = Product(merchant_id=merchant.id, brand_id=brand.id, category_id=cat.id, name="Linen Kurta", slug="linen", style_code="S1", mrp=2000, selling_price=1500, status="approved", is_active=True)
    draft = Product(merchant_id=merchant.id, brand_id=brand.id, category_id=cat.id, name="Draft Tee", slug="draft", style_code="S2", mrp=900, selling_price=700, status="draft", is_active=True)
    admin = User(name="Root", email="root@x.test", password="x", phone="+919000000001", role="super_admin")
    owner = User(name="Owner", email="owner@x.test", password="x", phone="+919000000002", role="merchant", merchant_id=merchant.id, is_merchant_owner=True)
    db.add_all([live, draft, admin, owner])
    db.commit()
    ids = {"live": live.id, "draft": draft.id}
    tokens = {name: {"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"} for name, u in (("admin", admin), ("owner", owner))}
    db.close()

    yield {"client": TestClient(app), "ids": ids, "h": tokens, "deleted": deleted, "Session": Session}
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def do_import(env, file_id, product="live", publish=True):
    return env["client"].post(f"/api/superadmin/drive/videos/{file_id}/import", json={"product_id": env["ids"][product], "publish": publish}, headers=env["h"]["admin"])


def test_admin_lists_folder_videos_with_previews(env):
    resp = env["client"].get("/api/superadmin/drive/videos", headers=env["h"]["admin"])
    assert resp.status_code == 200
    videos = {v["file_id"]: v for v in resp.json()["data"]}
    assert set(videos) == {"vid-1", "vid-2"}  # only the reels folder
    v1 = videos["vid-1"]
    assert v1["is_vertical"] and v1["duration_seconds"] == 18.5 and v1["imported_reel"] is None
    assert env["client"].get(v1["preview_url"]).content == MP4
    # Tampered signature is refused.
    assert env["client"].get(v1["preview_url"].replace("sig=", "sig=0")).status_code == 404


def test_import_publishes_to_every_feed(env):
    c = env["client"]
    resp = do_import(env, "vid-1")
    assert resp.status_code == 200, resp.text
    reel = resp.json()["data"]
    assert reel["source"] == "drive" and reel["is_published"] and reel["ai_model"]["id"] is None

    # Buyer feed: public, playable, shoppable.
    feed = c.get("/api/feed/reels").json()["data"]
    assert [r["id"] for r in feed] == [reel["id"]]
    assert feed[0]["product"]["name"] == "Linen Kurta"
    assert c.get(feed[0]["video_url"]).content == MP4

    # Merchant feed: their reel, with a signed preview.
    mine = c.get("/api/merchant/reels?media_type=video", headers=env["h"]["owner"]).json()["data"]
    assert mine[0]["id"] == reel["id"] and mine[0]["source"] == "drive"
    assert c.get(mine[0]["video_url"]).content == MP4

    # Super admin reel list.
    admin_reels = c.get("/api/superadmin/reels", headers=env["h"]["admin"]).json()["data"]
    assert admin_reels[0]["id"] == reel["id"] and admin_reels[0]["video_url"]

    # Library now marks the file as imported; a second import is refused.
    listed = {v["file_id"]: v for v in c.get("/api/superadmin/drive/videos", headers=env["h"]["admin"]).json()["data"]}
    assert listed["vid-1"]["imported_reel"]["id"] == reel["id"]
    assert do_import(env, "vid-1").status_code == 409


def test_unpublishable_product_imports_as_draft(env):
    resp = do_import(env, "vid-2", product="draft")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_published"] is False
    assert "not published" in resp.json()["message"]
    assert env["client"].get("/api/feed/reels").json()["data"] == []


def test_only_readable_videos_can_be_imported(env, monkeypatch):
    monkeypatch.setitem(DRIVE, "a-document", {"id": "a-document", "name": "notes.pdf", "mimeType": "application/pdf", "parents": [FOLDER]})
    assert do_import(env, "a-document").status_code == 404
    assert do_import(env, "does-not-exist").status_code == 404
    # A video shared by link (outside the folder) is importable.
    assert do_import(env, "elsewhere").status_code == 200


def test_lookup_by_drive_link(env, monkeypatch):
    c, h = env["client"], env["h"]["admin"]
    for link in ("https://drive.google.com/file/d/vid-1abcdefgh/view?usp=sharing", "https://drive.google.com/open?id=vid-1abcdefgh", "vid-1abcdefgh"):
        monkeypatch.setitem(DRIVE, "vid-1abcdefgh", {**DRIVE["vid-1"], "id": "vid-1abcdefgh"})
        resp = c.get("/api/superadmin/drive/lookup", params={"link": link}, headers=h)
        assert resp.status_code == 200, (link, resp.text)
        assert resp.json()["data"]["file_id"] == "vid-1abcdefgh"
    assert c.get("/api/superadmin/drive/lookup", params={"link": "https://example.com/nope"}, headers=h).status_code == 422
    assert c.get("/api/superadmin/drive/lookup", params={"link": "https://drive.google.com/file/d/missing12345/view"}, headers=h).status_code == 404


def test_only_super_admin_can_browse_or_import(env):
    c = env["client"]
    assert c.get("/api/superadmin/drive/videos", headers=env["h"]["owner"]).status_code == 403
    assert c.post(f"/api/superadmin/drive/videos/vid-1/import", json={"product_id": env["ids"]["live"]}, headers=env["h"]["owner"]).status_code == 403


def test_merchant_delete_never_deletes_the_drive_original(env):
    reel_id = do_import(env, "vid-1").json()["data"]["id"]
    resp = env["client"].delete(f"/api/merchant/try-ons/{reel_id}", headers=env["h"]["owner"])
    assert resp.status_code == 200
    assert env["deleted"] == []
    db = env["Session"]()
    assert db.get(ProductTryOn, reel_id) is None
    db.close()


def test_drive_not_connected_is_reported(env, monkeypatch):
    monkeypatch.setattr(drive_storage, "can_read", lambda: False)
    resp = env["client"].get("/api/superadmin/drive/videos", headers=env["h"]["admin"])
    assert resp.status_code == 503 and "GOOGLE_SERVICE_ACCOUNT_FILE" in resp.json()["message"]
