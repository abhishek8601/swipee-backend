from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.ai_model import ProductTryOn
from app.services import drive_storage, reel_service

router = APIRouter(tags=["reels"])


@router.get("/reels/{reel_id}/video")
async def reel_video(
    reel_id: int,
    request: Request,
    exp: Optional[int] = None,
    sig: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Stream a reel's MP4.

    Feed-eligible (published) reels are public. Anything else needs the
    short-lived signature the owner's merchant API hands out, because a
    <video> tag cannot send a bearer token.
    """
    if reel_service.verify_signature(reel_id, exp, sig):
        reel = db.get(ProductTryOn, reel_id)
    else:
        reel = reel_service.feed_query(db).filter(ProductTryOn.id == reel_id).first()
    if not reel or reel.media_type != "video":
        raise HTTPException(status_code=404, detail="Video not found.")

    local = reel_service.video_file(reel)
    if local:
        # FileResponse honours Range requests, which video seeking relies on.
        return FileResponse(local, media_type="video/mp4", headers={"Cache-Control": "private, max-age=300"})

    if reel.storage_status == "uploaded" and reel.storage_file_id and drive_storage.is_configured():
        file_id = reel.storage_file_id
        db.close()  # don't hold a connection for the length of the stream
        try:
            status, headers, body = await drive_storage.stream_file(file_id, request.headers.get("range"))
        except drive_storage.DriveError:
            raise HTTPException(status_code=502, detail="The video could not be fetched from storage.")
        return StreamingResponse(body, status_code=status, media_type="video/mp4", headers={**headers, "Cache-Control": "private, max-age=300"})

    raise HTTPException(status_code=404, detail="Video file is not available.")
