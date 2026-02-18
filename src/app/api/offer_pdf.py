"""
Offer PDF endpoint — streams the current active offer PDF from the NAS.

Security : JWT required. No customer-specific check (offer is global).
           The client never sees internal filesystem paths.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..core.auth import User, get_current_user
from ..services.offer_service import get_active_offer_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["offers"])


@router.get("/offers/current")
async def get_current_offer(
    current_user: User = Depends(get_current_user),
):
    """
    Download the current active offer PDF.

    - 401: missing / invalid JWT (handled by auth dependency)
    - 404: no active offer found on the filesystem
    - 200: streams the PDF file inline
    """
    offer_path = await get_active_offer_path()

    if offer_path is None:
        raise HTTPException(status_code=404, detail="No active offer available")

    # offer_path.name == "oferta_YYYYMMDD.pdf" — never the full internal path
    filename = offer_path.name

    return FileResponse(
        path=offer_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
