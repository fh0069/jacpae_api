"""
Daily offer notification job.

Checks for an active offer PDF on the NAS filesystem and, if one is found,
inserts a deduplicated notification for every active customer profile in
Supabase. The source_key ensures the notification is sent at most once per
offer expiry date regardless of how many times the job runs.

When a new notification is inserted for a user, a single FCM push is
dispatched as a wake-up signal. A push failure never affects persistence.
"""
import logging
from datetime import date
from pathlib import Path

from ..core.supabase_admin import (
    NotificationInsert,
    SupabaseUnavailableError,
    fetch_active_user_ids,
    insert_notification,
)
from ..services.fcm_service import send_push_to_user
from ..services.offer_service import get_active_offer_path

logger = logging.getLogger(__name__)


def _parse_expiry(offer_path: Path) -> date:
    """
    Extract the expiry date from an offer filename.

    Expects a Path whose stem is ``oferta_YYYYMMDD`` (already validated by
    offer_service before being returned).
    """
    date_str = offer_path.stem.split("_", 1)[1]  # "oferta_20260301" → "20260301"
    return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def _build_notification(user_id: str, expiry: date) -> NotificationInsert:
    """Build a NotificationInsert for the active offer."""
    return NotificationInsert(
        user_id=user_id,
        type="oferta",
        title="🎉 Nueva oferta disponible",
        body=f"Hay una nueva oferta disponible hasta el {expiry:%d/%m/%Y}.",
        event_date=expiry,
        data={"expiry": expiry.isoformat()},
        source_key=f"oferta:{expiry.isoformat()}",
    )


async def run_offer_job() -> dict[str, int]:
    """
    Main entry point for the daily offer notification job.

    Returns:
        Summary dict with keys:
          total_users, inserted, deduped, errors,
          push_sent, push_failed, push_invalidated
    """
    summary: dict[str, int] = {
        "total_users": 0,
        "inserted": 0,
        "deduped": 0,
        "errors": 0,
        "push_sent": 0,
        "push_failed": 0,
        "push_invalidated": 0,
    }

    offer_path = await get_active_offer_path()
    if offer_path is None:
        logger.info("Offer job: no active offer found, nothing to do")
        return summary

    expiry = _parse_expiry(offer_path)

    logger.debug("Offer job: active offer expiry=%s", expiry.isoformat())

    try:
        user_ids = await fetch_active_user_ids()
    except SupabaseUnavailableError:
        logger.error("Offer job aborted: cannot fetch active user ids from Supabase")
        summary["errors"] = 1
        return summary

    summary["total_users"] = len(user_ids)

    if not user_ids:
        logger.info("Offer job: no active users found")
        return summary

    for user_id in user_ids:
        notification = _build_notification(user_id, expiry)
        try:
            was_inserted = await insert_notification(notification)
            if was_inserted:
                summary["inserted"] += 1
                push_result = await send_push_to_user(
                    user_id=user_id,
                    title="Tienes notificaciones nuevas",
                    body="",
                    data={"type": "oferta"},
                )
                summary["push_sent"] += push_result.sent
                summary["push_failed"] += push_result.failed
                summary["push_invalidated"] += push_result.invalidated
            else:
                summary["deduped"] += 1
        except SupabaseUnavailableError:
            logger.error(
                "Offer job: Supabase unavailable inserting source_key=%s",
                notification.source_key,
            )
            summary["errors"] += 1

    logger.info(
        "Offer job completed: users=%d inserted=%d deduped=%d errors=%d "
        "push_sent=%d push_failed=%d push_invalidated=%d",
        summary["total_users"],
        summary["inserted"],
        summary["deduped"],
        summary["errors"],
        summary["push_sent"],
        summary["push_failed"],
        summary["push_invalidated"],
    )
    return summary
