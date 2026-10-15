"""Google Drive storage for generated reel videos (Drive REST v3, no SDK).

Auth: a service-account key file (GOOGLE_SERVICE_ACCOUNT_FILE) or an OAuth
refresh token (GOOGLE_DRIVE_CLIENT_ID / _SECRET / _REFRESH_TOKEN). Tokens stay
server-side; nothing here is ever returned to a client. Files are created
private: playback goes through the backend's access-controlled video endpoint,
never a public Drive link.
"""
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
import jwt

from app.core.config import settings

logger = logging.getLogger("swipee.drive")

TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_URI = "https://www.googleapis.com/upload/drive/v3/files"
FILES_URI = "https://www.googleapis.com/drive/v3/files"
CHUNK_SIZE = 8 * 1024 * 1024  # must be a multiple of 256 KiB
MAX_RETRIES = 5
RETRYABLE = {408, 429, 500, 502, 503, 504}


class DriveError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def auth_mode() -> Optional[str]:
    if settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        return "service_account"
    if settings.GOOGLE_DRIVE_CLIENT_ID and settings.GOOGLE_DRIVE_CLIENT_SECRET and settings.GOOGLE_DRIVE_REFRESH_TOKEN:
        return "oauth"
    return None


def is_configured() -> bool:
    """Uploads need a destination folder as well as credentials."""
    return bool(settings.GOOGLE_DRIVE_FOLDER_ID and auth_mode())


def can_read() -> bool:
    """Streaming or listing existing files only needs credentials."""
    return bool(auth_mode())


def reels_folder_id() -> str:
    return settings.GOOGLE_DRIVE_REELS_FOLDER_ID or settings.GOOGLE_DRIVE_FOLDER_ID


def missing_configuration() -> list[str]:
    missing = []
    if not settings.GOOGLE_DRIVE_FOLDER_ID:
        missing.append("GOOGLE_DRIVE_FOLDER_ID")
    if not auth_mode():
        missing.append("GOOGLE_SERVICE_ACCOUNT_FILE (or GOOGLE_DRIVE_CLIENT_ID + GOOGLE_DRIVE_CLIENT_SECRET + GOOGLE_DRIVE_REFRESH_TOKEN)")
    return missing


_token: dict = {"value": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


def _service_account_assertion() -> tuple[str, str]:
    path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DriveError(f"Cannot read Google service account file ({e.__class__.__name__}).")
    now = int(time.time())
    claims = {
        "iss": info["client_email"],
        "scope": settings.GOOGLE_DRIVE_SCOPE,
        "aud": info.get("token_uri", TOKEN_URI),
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, info["private_key"], algorithm="RS256", headers={"kid": info.get("private_key_id")})
    return assertion, info.get("token_uri", TOKEN_URI)


async def _access_token(client: httpx.AsyncClient, force_refresh: bool = False) -> str:
    async with _token_lock:
        if not force_refresh and _token["value"] and _token["expires_at"] - 60 > time.time():
            return _token["value"]
        mode = auth_mode()
        if mode == "service_account":
            assertion, token_uri = _service_account_assertion()
            data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        elif mode == "oauth":
            token_uri = TOKEN_URI
            data = {
                "grant_type": "refresh_token",
                "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                "refresh_token": settings.GOOGLE_DRIVE_REFRESH_TOKEN,
            }
        else:
            raise DriveError("Google Drive credentials are not configured.")
        resp = await client.post(token_uri, data=data)
        if resp.status_code != 200:
            # Body may echo request details; log only the error code.
            code = resp.json().get("error") if resp.headers.get("content-type", "").startswith("application/json") else None
            raise DriveError(
                f"Google token request failed (HTTP {resp.status_code}{', ' + code if code else ''}). "
                "Check that the Drive credentials are valid and not revoked.",
                retryable=resp.status_code in RETRYABLE,
            )
        body = resp.json()
        _token["value"] = body["access_token"]
        _token["expires_at"] = time.time() + int(body.get("expires_in", 3600))
        return _token["value"]


async def _request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Authorized request with one token refresh on 401 and backoff on retryable codes."""
    base_headers = kwargs.pop("headers", {})
    refreshed = False
    for attempt in range(MAX_RETRIES):
        token = await _access_token(client, force_refresh=refreshed)
        headers = {**base_headers, "Authorization": f"Bearer {token}"}
        try:
            resp = await client.request(method, url, headers=headers, **kwargs)
        except httpx.TransportError as e:
            if attempt == MAX_RETRIES - 1:
                raise DriveError(f"Network error talking to Google Drive ({e.__class__.__name__}).", retryable=True)
            await asyncio.sleep(2 ** attempt)
            continue
        if resp.status_code == 401 and not refreshed:
            refreshed = True
            continue
        if resp.status_code in RETRYABLE and attempt < MAX_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)
            continue
        return resp
    return resp


async def upload_video(local_path: Path, name: str, app_properties: dict) -> dict:
    """Resumable upload into GOOGLE_DRIVE_FOLDER_ID. Returns {id, name, size}."""
    if not is_configured():
        raise DriveError("Google Drive is not configured: missing " + ", ".join(missing_configuration()))
    total = local_path.stat().st_size
    metadata = {
        "name": name,
        "parents": [settings.GOOGLE_DRIVE_FOLDER_ID],
        "mimeType": "video/mp4",
        "appProperties": {k: str(v) for k, v in app_properties.items()},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        start = await _request(
            client, "POST", UPLOAD_URI,
            params={"uploadType": "resumable", "supportsAllDrives": "true"},
            headers={"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(total)},
            json=metadata,
        )
        if start.status_code != 200 or "location" not in start.headers:
            raise DriveError(_drive_error("start upload", start), retryable=start.status_code in RETRYABLE)
        session_uri = start.headers["location"]

        offset = 0
        failures = 0
        with open(local_path, "rb") as fh:
            while True:
                fh.seek(offset)
                chunk = fh.read(CHUNK_SIZE)
                end = offset + len(chunk) - 1
                try:
                    # The session URI itself authorizes the upload.
                    resp = await client.put(
                        session_uri, content=chunk,
                        headers={"Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{total}"},
                    )
                except httpx.TransportError:
                    resp = None
                if resp is not None and resp.status_code in (200, 201):
                    result = resp.json()
                    break
                if resp is not None and resp.status_code == 308:
                    offset = _next_offset(resp)
                    failures = 0
                    continue
                if resp is not None and resp.status_code not in RETRYABLE:
                    raise DriveError(_drive_error("upload chunk", resp))
                failures += 1
                if failures >= MAX_RETRIES:
                    raise DriveError("Google Drive upload kept failing; retry later.", retryable=True)
                await asyncio.sleep(2 ** failures)
                # Ask Drive how much it actually received before resuming.
                status = await client.put(session_uri, headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"})
                if status.status_code in (200, 201):
                    result = status.json()
                    break
                if status.status_code == 308:
                    offset = _next_offset(status)

        info = await _request(client, "GET", f"{FILES_URI}/{result['id']}", params={"fields": "id,name,size", "supportsAllDrives": "true"})
        if info.status_code == 200:
            result = info.json()
        if result.get("size") and int(result["size"]) != total:
            raise DriveError(f"Drive reports {result['size']} bytes but {total} were sent.", retryable=True)
        return result


def _next_offset(resp: httpx.Response) -> int:
    rng = resp.headers.get("range")  # e.g. "bytes=0-8388607"
    return int(rng.split("-")[-1]) + 1 if rng else 0


def _drive_error(action: str, resp: httpx.Response) -> str:
    reason = ""
    try:
        err = resp.json().get("error", {})
        reason = err.get("message", "") if isinstance(err, dict) else str(err)
    except ValueError:
        pass
    hint = ""
    if "storage quota" in reason.lower():
        hint = " Service accounts have no My Drive quota: put the folder in a Shared Drive or use OAuth credentials."
    elif resp.status_code == 404:
        hint = " Check GOOGLE_DRIVE_FOLDER_ID and that the credentials can access that folder."
    return f"Google Drive could not {action} (HTTP {resp.status_code}). {reason}{hint}".strip()


async def stream_file(file_id: str, range_header: Optional[str]) -> tuple[int, dict, AsyncIterator[bytes]]:
    """Proxy a Drive file's bytes (honouring Range) for the video endpoint."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
    token = await _access_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    if range_header:
        headers["Range"] = range_header
    req = client.build_request("GET", f"{FILES_URI}/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, headers=headers)
    resp = await client.send(req, stream=True)
    if resp.status_code not in (200, 206):
        await resp.aclose()
        await client.aclose()
        raise DriveError(f"Google Drive download failed (HTTP {resp.status_code}).", retryable=resp.status_code in RETRYABLE)
    passthrough = {k: v for k, v in resp.headers.items() if k.lower() in ("content-length", "content-range", "accept-ranges")}

    async def body():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return resp.status_code, passthrough, body()


async def delete_file(file_id: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await _request(client, "DELETE", f"{FILES_URI}/{file_id}", params={"supportsAllDrives": "true"})
        if resp.status_code not in (204, 404):
            raise DriveError(_drive_error("delete file", resp))


VIDEO_FIELDS = "id,name,mimeType,size,createdTime,modifiedTime,parents,videoMediaMetadata(width,height,durationMillis),hasThumbnail,trashed"


async def list_folder_videos(folder_id: str) -> list[dict]:
    """Every (non-trashed) video directly inside a Drive folder, newest first."""
    if not can_read():
        raise DriveError("Google Drive credentials are not configured.")
    files: list[dict] = []
    page_token = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "q": f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false",
                "fields": f"nextPageToken,files({VIDEO_FIELDS})",
                "orderBy": "createdTime desc",
                "pageSize": "200",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = await _request(client, "GET", FILES_URI, params=params)
            if resp.status_code != 200:
                raise DriveError(_drive_error("list the reels folder", resp), retryable=resp.status_code in RETRYABLE)
            body = resp.json()
            files.extend(body.get("files", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return files


async def get_file(file_id: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await _request(client, "GET", f"{FILES_URI}/{file_id}", params={"fields": VIDEO_FIELDS, "supportsAllDrives": "true"})
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise DriveError(_drive_error("read the file", resp), retryable=resp.status_code in RETRYABLE)
    return resp.json()


async def thumbnail_bytes(file_id: str) -> Optional[tuple[bytes, str]]:
    """Drive's generated preview frame for a video, or None if it has none yet."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        meta = await _request(client, "GET", f"{FILES_URI}/{file_id}", params={"fields": "thumbnailLink", "supportsAllDrives": "true"})
        link = meta.json().get("thumbnailLink") if meta.status_code == 200 else None
        if not link:
            return None
        # thumbnailLink is short-lived and needs the same bearer token for private files.
        resp = await _request(client, "GET", link.replace("=s220", "=s640"))
        if resp.status_code != 200:
            return None
        return resp.content, resp.headers.get("content-type", "image/jpeg")
