"""Image-to-video providers for reels.

Only real providers live here: there is deliberately no stub that returns a
canned clip. With VIDEO_PROVIDER unset, `get_provider()` returns None and the
API refuses to queue reels.
"""
import base64
import io
from dataclasses import dataclass
from typing import Optional

import httpx
from PIL import Image

from app.core.config import settings

RETRYABLE = {408, 429, 500, 502, 503, 504}


class VideoProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class JobState:
    state: str  # running, succeeded, failed
    output_url: Optional[str] = None
    error: Optional[str] = None


def _keyframe_data_uri(image_path, max_bytes: int = 250 * 1024) -> str:
    """Portrait JPEG under ~250 KB, the size Replicate accepts inline as a data URI."""
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((768, 1024))
    for quality in (90, 80, 70, 60, 50):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            break
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class ReplicateProvider:
    name = "replicate"
    base = "https://api.replicate.com/v1"

    def missing_configuration(self) -> list[str]:
        missing = []
        if not settings.REPLICATE_API_TOKEN:
            missing.append("REPLICATE_API_TOKEN")
        if not settings.REPLICATE_VIDEO_MODEL:
            missing.append("REPLICATE_VIDEO_MODEL")
        return missing

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.REPLICATE_API_TOKEN}", "Content-Type": "application/json"}

    @staticmethod
    def _raise_for(resp: httpx.Response, action: str):
        if resp.status_code in (401, 403):
            raise VideoProviderError(f"Replicate rejected the API token while trying to {action} (HTTP {resp.status_code}). Check REPLICATE_API_TOKEN.")
        if resp.status_code == 404:
            raise VideoProviderError(f"Replicate model '{settings.REPLICATE_VIDEO_MODEL}' was not found. Check REPLICATE_VIDEO_MODEL.")
        if resp.status_code == 422:
            detail = resp.json().get("detail", "") if resp.content else ""
            raise VideoProviderError(f"Replicate refused the input: {detail}. Check REPLICATE_IMAGE_INPUT_KEY / REPLICATE_DURATION_INPUT_KEY for this model.")
        raise VideoProviderError(f"Replicate could not {action} (HTTP {resp.status_code}).", retryable=resp.status_code in RETRYABLE)

    async def start(self, keyframe_path, prompt: str, duration_seconds: Optional[int]) -> str:
        payload = {settings.REPLICATE_IMAGE_INPUT_KEY: _keyframe_data_uri(keyframe_path), "prompt": prompt}
        if settings.REPLICATE_DURATION_INPUT_KEY and duration_seconds:
            payload[settings.REPLICATE_DURATION_INPUT_KEY] = duration_seconds
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.base}/models/{settings.REPLICATE_VIDEO_MODEL}/predictions", headers=self._headers(), json={"input": payload})
        except httpx.TransportError as e:
            raise VideoProviderError(f"Network error reaching Replicate ({e.__class__.__name__}).", retryable=True)
        if resp.status_code not in (200, 201):
            self._raise_for(resp, "start the video job")
        return resp.json()["id"]

    async def poll(self, job_id: str) -> JobState:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.base}/predictions/{job_id}", headers=self._headers())
        except httpx.TransportError as e:
            raise VideoProviderError(f"Network error reaching Replicate ({e.__class__.__name__}).", retryable=True)
        if resp.status_code != 200:
            self._raise_for(resp, "read the video job")
        body = resp.json()
        status = body.get("status")
        if status == "succeeded":
            output = body.get("output")
            url = output[0] if isinstance(output, list) and output else output
            if not isinstance(url, str):
                return JobState("failed", error="Replicate finished without a video URL.")
            return JobState("succeeded", output_url=url)
        if status in ("failed", "canceled"):
            return JobState("failed", error=str(body.get("error") or f"Replicate job {status}."))
        return JobState("running")


PROVIDERS = {"replicate": ReplicateProvider}


def get_provider():
    cls = PROVIDERS.get(settings.VIDEO_PROVIDER.strip().lower())
    return cls() if cls else None


def missing_configuration() -> list[str]:
    provider = get_provider()
    if not provider:
        return [f"VIDEO_PROVIDER (supported: {', '.join(PROVIDERS)})"]
    return provider.missing_configuration()


def is_configured() -> bool:
    return not missing_configuration()
