"""Merchant reel pipeline: AI model + product -> keyframe -> video -> Google Drive.

A reel is a ProductTryOn row with media_type="video". Two independent status
tracks live on it:

  status          queued -> processing -> completed | failed   (generation)
  storage_status  pending -> uploading -> uploaded | failed | not_configured

Work runs in FastAPI background tasks (the project's existing job mechanism).
Every step is resumable from the row: the keyframe is rendered once, the
provider job id is saved before polling, and a worker lease (lease_until)
stops two workers from driving the same reel. No DB transaction is held
across a network call.
"""
import asyncio
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import or_, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.enums import MerchantStatus, ProductStatus
from app.models.ai_model import ProductTryOn
from app.models.merchant import Merchant
from app.models.product import Product
from app.services import drive_storage, video_provider
from app.services.tryon_service import TryOnService

logger = logging.getLogger("swipee.reels")

LEASE_SECONDS = 300  # renewed on every poll; must outlast the keyframe render
UPLOAD_LEASE_SECONDS = 1800
POLL_INTERVAL_SECONDS = 5
SCENE_PROMPTS = {
    "studio": "minimal photo studio with soft key light",
    "street": "sunlit urban street",
    "runway": "fashion runway with audience bokeh",
    "festive": "festive decorated venue with warm lights",
}
ACTIVE_STATUSES = ("queued", "processing")
BLOCKED_MODERATION = ("rejected", "disabled")


# ---------------------------------------------------------------- media access

def video_file(reel: ProductTryOn) -> Optional[Path]:
    if not reel.video_path:
        return None
    path = settings.PRIVATE_STORAGE_DIR / reel.video_path
    return path if path.is_file() else None


def is_playable(reel: ProductTryOn) -> bool:
    return bool(video_file(reel)) or (reel.storage_status == "uploaded" and bool(reel.storage_file_id))


def _signature(reel_id: int, expires: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"reel-video:{reel_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def poster_url(reel: ProductTryOn) -> Optional[str]:
    """Cover frame: the AI keyframe for generated reels, else the product's main image."""
    if reel.thumb_path:
        return f"/storage/{reel.thumb_path}"
    image = reel.product.primary_image if reel.product else None
    return f"/storage/{image.image_path}" if image else None


def signed_video_url(reel: ProductTryOn, ttl_seconds: int = 3600) -> Optional[str]:
    """Short-lived URL a <video> tag can load without an Authorization header."""
    if not is_playable(reel):
        return None
    expires = int(time.time()) + ttl_seconds
    return f"/api/reels/{reel.id}/video?exp={expires}&sig={_signature(reel.id, expires)}"


def verify_signature(reel_id: int, exp: Optional[int], sig: Optional[str]) -> bool:
    if not exp or not sig or exp < time.time():
        return False
    return hmac.compare_digest(_signature(reel_id, exp), sig)


# Raw Drive files (the super admin's import library) get their own signature
# namespace so a reel link can never be replayed as a Drive-file link or back.
def _drive_signature(file_id: str, kind: str, expires: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"drive-file:{kind}:{file_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def signed_drive_url(file_id: str, kind: str, ttl_seconds: int = 3600) -> str:
    """kind is "video" or "thumbnail"."""
    expires = int(time.time()) + ttl_seconds
    return f"/api/reels/drive/{file_id}/{kind}?exp={expires}&sig={_drive_signature(file_id, kind, expires)}"


def verify_drive_signature(file_id: str, kind: str, exp: Optional[int], sig: Optional[str]) -> bool:
    if not exp or not sig or exp < time.time():
        return False
    return hmac.compare_digest(_drive_signature(file_id, kind, exp), sig)


# ------------------------------------------------------------ business rules

def product_publishable(product: Optional[Product]) -> bool:
    return bool(
        product and product.deleted_at is None and product.is_active
        and product.status == ProductStatus.APPROVED.value
        and product.merchant and product.merchant.status == MerchantStatus.APPROVED.value
        and product.merchant.deleted_at is None
    )


def publish_blockers(reel: ProductTryOn) -> list[str]:
    reasons = []
    if reel.media_type != "video":
        reasons.append("Only video reels can be published to the buyer feed.")
    if reel.status != "completed":
        reasons.append("Video generation has not completed.")
    elif not is_playable(reel):
        reasons.append("The video file is not stored or playable.")
    if reel.moderation_status in BLOCKED_MODERATION:
        reasons.append(f"This reel was {reel.moderation_status} by moderation and cannot be republished.")
    if reel.is_placeholder and not settings.TRYON_ALLOW_PLACEHOLDER_PUBLISH:
        reasons.append(
            "This reel's keyframe came from a placeholder try-on driver (it does not show the real garment), "
            "so it cannot go to shoppers. Configure a real try-on driver, or set TRYON_ALLOW_PLACEHOLDER_PUBLISH=true for demos."
        )
    if not product_publishable(reel.product):
        reasons.append("The product must be approved and active, and the merchant approved, before its reel can be published.")
    return reasons


def feed_query(db: Session):
    """Reels a buyer may see. Mirrors publish_blockers so a later change to the
    product, merchant or moderation state removes the reel from the feed."""
    q = (
        db.query(ProductTryOn)
        .join(Product, Product.id == ProductTryOn.product_id)
        .join(Merchant, Merchant.id == ProductTryOn.merchant_id)
        .filter(
            ProductTryOn.media_type == "video",
            ProductTryOn.status == "completed",
            ProductTryOn.is_published.is_(True),
            or_(ProductTryOn.moderation_status.is_(None), ProductTryOn.moderation_status.notin_(BLOCKED_MODERATION)),
            or_(ProductTryOn.video_path.isnot(None), ProductTryOn.storage_status == "uploaded"),
            Product.merchant_id == ProductTryOn.merchant_id,
            Product.status == ProductStatus.APPROVED.value,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
            Merchant.status == MerchantStatus.APPROVED.value,
            Merchant.deleted_at.is_(None),
        )
    )
    if not settings.TRYON_ALLOW_PLACEHOLDER_PUBLISH:
        q = q.filter(or_(ProductTryOn.is_placeholder.is_(False), ProductTryOn.is_placeholder.is_(None)))
    return q


# ------------------------------------------------------------------- leases

def _claim(db: Session, reel_id: int, seconds: int = LEASE_SECONDS) -> bool:
    now = datetime.utcnow()
    result = db.execute(
        update(ProductTryOn)
        .where(ProductTryOn.id == reel_id, or_(ProductTryOn.lease_until.is_(None), ProductTryOn.lease_until < now))
        .values(lease_until=now + timedelta(seconds=seconds))
    )
    db.commit()
    return result.rowcount == 1


def _renew(db: Session, reel_id: int):
    db.execute(update(ProductTryOn).where(ProductTryOn.id == reel_id).values(lease_until=datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)))
    db.commit()


def _release(db: Session, reel_id: int):
    db.execute(update(ProductTryOn).where(ProductTryOn.id == reel_id).values(lease_until=None))
    db.commit()


# ---------------------------------------------------------------- pipeline

def video_prompt(reel: ProductTryOn) -> str:
    model = reel.ai_model
    who = "male" if model.gender == "male" else ("female" if model.gender == "female" else "")
    scene = SCENE_PROMPTS.get(reel.scene_style or "studio", SCENE_PROMPTS["studio"])
    return (
        f"Vertical 9:16 fashion reel. An Indian {who} model ({model.body_type or 'fit'} build) wearing {reel.product.name}, "
        f"in a {scene}. Slow confident walk toward camera, a gentle turn to show the garment's fit and drape, "
        "natural fabric movement, cinematic lighting, photorealistic."
    )


async def _with_retries(fn, *args, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return await fn(*args)
        except video_provider.VideoProviderError as e:
            if not e.retryable or attempt == attempts - 1:
                raise
            await asyncio.sleep(2 ** (attempt + 1))


async def _download_video(url: str, dest: Path) -> int:
    os.makedirs(dest.parent, exist_ok=True)
    tmp = dest.with_suffix(".part")
    size = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise video_provider.VideoProviderError(f"Could not download the generated video (HTTP {resp.status_code}).", retryable=True)
                with open(tmp, "wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > settings.VIDEO_MAX_BYTES:
                            raise video_provider.VideoProviderError("Generated video exceeds VIDEO_MAX_BYTES.")
                        fh.write(chunk)
        with open(tmp, "rb") as fh:
            head = fh.read(12)
        # MP4/MOV files carry an 'ftyp' box at byte 4.
        if size == 0 or head[4:8] != b"ftyp":
            raise video_provider.VideoProviderError("Provider output is not an MP4 video.")
        os.replace(tmp, dest)
        return size
    finally:
        if tmp.exists():
            tmp.unlink()


def _fail(db: Session, reel_id: int, message: str, clear_job: bool = False):
    db.rollback()
    reel = db.get(ProductTryOn, reel_id)
    if reel:
        reel.status = "failed"
        reel.error_message = message[:2000]
        if clear_job:
            reel.video_job_id = None
        db.commit()


async def process_reel(reel_id: int):
    db = SessionLocal()
    try:
        if not _claim(db, reel_id):
            return  # another worker holds it
        try:
            await _generate(db, reel_id)
        finally:
            _release(db, reel_id)
        reel = db.get(ProductTryOn, reel_id)
        if reel and reel.status == "completed" and reel.storage_status in (None, "pending"):
            await upload_reel(reel_id, db=db)
    finally:
        db.close()


async def _generate(db: Session, reel_id: int):
    reel = db.get(ProductTryOn, reel_id)
    if not reel or reel.media_type != "video" or reel.status not in ACTIVE_STATUSES:
        return
    started = time.time()
    if reel.status == "queued":
        reel.generation_attempts = (reel.generation_attempts or 0) + 1
    reel.status = "processing"
    reel.error_message = None
    db.commit()

    provider = video_provider.get_provider()
    if not provider or not video_provider.is_configured():
        return _fail(db, reel_id, "Video provider not configured: set " + ", ".join(video_provider.missing_configuration()))

    # Locals only from here on: touching an expired ORM attribute after a
    # commit would silently open a new transaction across the next await.
    scene = SCENE_PROMPTS.get(reel.scene_style or "studio", SCENE_PROMPTS["studio"])
    still_inputs = TryOnService.still_inputs(reel)
    keyframe_rel = reel.result_path
    job_id = reel.video_job_id
    prompt = video_prompt(reel)
    duration = reel.duration_seconds
    merchant_id = reel.merchant_id
    db.commit()

    try:
        # 1. Keyframe: the AI model wearing the product.
        if not keyframe_rel:
            still = await TryOnService.render_still(still_inputs, scene)
            keyframe_rel = still["path"]
            db.execute(update(ProductTryOn).where(ProductTryOn.id == reel_id).values(
                result_path=keyframe_rel, thumb_path=keyframe_rel, provider=still["provider"],
                is_placeholder=still["is_placeholder"], prompt_used=still["prompt"]))
            db.commit()

        # 2. Video job, saved before polling so a retry resumes it instead of paying twice.
        if not job_id:
            job_id = await _with_retries(provider.start, settings.STORAGE_DIR / keyframe_rel, prompt, duration)
            db.execute(update(ProductTryOn).where(ProductTryOn.id == reel_id).values(video_job_id=job_id, video_provider=provider.name))
            db.commit()

        # 3. Poll until done.
        deadline = time.time() + settings.VIDEO_JOB_TIMEOUT_SECONDS
        transient_errors = 0
        while True:
            try:
                job = await provider.poll(job_id)
                transient_errors = 0
            except video_provider.VideoProviderError as e:
                if not e.retryable or transient_errors >= 5:
                    raise
                transient_errors += 1
                job = video_provider.JobState("running")
            if job.state == "succeeded":
                break
            if job.state == "failed":
                return _fail(db, reel_id, f"Video generation failed at the provider: {job.error}", clear_job=True)
            if time.time() > deadline:
                return _fail(db, reel_id, f"Video generation timed out after {settings.VIDEO_JOB_TIMEOUT_SECONDS}s; retry to resume provider job {job_id}.")
            _renew(db, reel_id)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        # 4. Download and validate.
        rel = f"reels/{merchant_id}/reel_{reel_id}_{int(time.time())}.mp4"
        await _download_video(job.output_url, settings.PRIVATE_STORAGE_DIR / rel)
        reel = db.get(ProductTryOn, reel_id)
        reel.video_path = rel
        reel.status = "completed"
        reel.error_message = None
        reel.latency_ms = int((time.time() - started) * 1000)
        reel.storage_status = "pending"
        db.commit()
    except video_provider.VideoProviderError as e:
        _fail(db, reel_id, str(e))
    except Exception as e:  # keyframe driver or unexpected failure
        logger.exception("Reel %s generation crashed", reel_id)
        _fail(db, reel_id, f"Reel generation failed: {e.__class__.__name__}: {e}")


async def upload_reel(reel_id: int, db: Optional[Session] = None):
    own = db is None
    db = db or SessionLocal()
    try:
        if not _claim(db, reel_id, UPLOAD_LEASE_SECONDS):
            return
        try:
            await _upload(db, reel_id)
        finally:
            _release(db, reel_id)
    finally:
        if own:
            db.close()


async def _upload(db: Session, reel_id: int):
    reel = db.get(ProductTryOn, reel_id)
    if not reel or reel.status != "completed" or reel.storage_status == "uploaded":
        return
    path = video_file(reel)
    if not path:
        reel.storage_status = "failed"
        reel.storage_error = "The local video file is missing; regenerate the reel."
        db.commit()
        return
    if not drive_storage.is_configured():
        reel.storage_status = "not_configured"
        reel.storage_error = "Google Drive not configured: set " + ", ".join(drive_storage.missing_configuration())
        db.commit()
        return

    reel.storage_status = "uploading"
    reel.storage_attempts = (reel.storage_attempts or 0) + 1
    reel.storage_error = None
    meta = {"reel_id": reel.id, "merchant_id": reel.merchant_id, "product_id": reel.product_id, "ai_model_id": reel.ai_model_id}
    name = f"swipee_reel_{reel.id}_merchant{reel.merchant_id}_product{reel.product_id}.mp4"
    db.commit()
    try:
        result = await drive_storage.upload_video(path, name, meta)
    except drive_storage.DriveError as e:
        db.rollback()
        reel = db.get(ProductTryOn, reel_id)
        reel.storage_status = "failed"
        reel.storage_error = str(e)[:2000]
        db.commit()
        return
    except Exception as e:
        logger.exception("Reel %s Drive upload crashed", reel_id)
        db.rollback()
        reel = db.get(ProductTryOn, reel_id)
        reel.storage_status = "failed"
        reel.storage_error = f"Upload failed: {e.__class__.__name__}"
        db.commit()
        return
    reel = db.get(ProductTryOn, reel_id)
    reel.storage_status = "uploaded"
    reel.storage_provider = "google_drive"
    reel.storage_file_id = result["id"]
    reel.stored_at = datetime.utcnow()
    reel.storage_error = None
    db.commit()


async def resume_pending_reels():
    """Pick up work interrupted by a restart (BackgroundTasks die with the process)."""
    db = SessionLocal()
    try:
        try:
            db.query(ProductTryOn.media_type, ProductTryOn.lease_until).limit(1).all()
        except DBAPIError:
            logger.error("product_try_ons is missing the reel columns; run `alembic upgrade head`.")
            return
        generating = [r.id for r in db.query(ProductTryOn.id).filter(
            ProductTryOn.media_type == "video", ProductTryOn.status.in_(ACTIVE_STATUSES))]
        uploading = [r.id for r in db.query(ProductTryOn.id).filter(
            ProductTryOn.media_type == "video", ProductTryOn.status == "completed",
            ProductTryOn.storage_status.in_(("pending", "uploading")))]
        # A lease left by a killed process would block these until it expires.
        if generating or uploading:
            db.execute(update(ProductTryOn).where(ProductTryOn.id.in_(generating + uploading)).values(lease_until=None))
            db.execute(update(ProductTryOn).where(ProductTryOn.id.in_(uploading), ProductTryOn.storage_status == "uploading").values(storage_status="pending"))
            db.commit()
    finally:
        db.close()
    for reel_id in generating:
        asyncio.create_task(process_reel(reel_id))
    for reel_id in uploading:
        asyncio.create_task(upload_reel(reel_id))
