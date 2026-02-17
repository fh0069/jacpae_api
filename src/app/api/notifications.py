"""
Notifications API - List and manage user notifications.

Security: JWT required. Only returns notifications belonging to the
authenticated user (filtered server-side via SERVICE_ROLE_KEY).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..core.auth import get_current_user, User
from ..core.supabase_admin import (
    Notification,
    SupabaseUnavailableError,
    fetch_notifications,
    mark_notification_read,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[Notification])
async def get_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> list[Notification]:
    """List notifications for the authenticated user (newest first)."""
    try:
        return await fetch_notifications(current_user.sub, limit, offset)
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Notification service unavailable")


@router.patch(
    "/notifications/{notification_id}/read",
    status_code=204,
    response_class=Response,
)
async def patch_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Mark a notification as read. Returns 204 on success, 404 if not found."""
    try:
        updated = await mark_notification_read(current_user.sub, notification_id)
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Notification service unavailable")

    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")

    return Response(status_code=204)
