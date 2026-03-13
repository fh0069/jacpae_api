"""Push service – business logic for device registration."""
import logging

from ..repositories.push_repository import get_device_by_token, insert_device, update_device

logger = logging.getLogger(__name__)


async def register_device(user_id: str, device_token: str, platform: str) -> None:
    """
    Register or reactivate a push notification device.

    - Token not found → insert new row (is_active=True, all timestamps = now)
    - Token found     → update user_id, is_active=True, updated_at, last_seen_at
                        Covers reinstall, user change, and reactivation.
    """
    existing = await get_device_by_token(device_token)

    if existing is None:
        await insert_device(user_id=user_id, device_token=device_token, platform=platform)
        logger.info("Device registered: user_id=%s platform=%s", user_id, platform)
    else:
        await update_device(device_id=existing["id"], user_id=user_id)
        logger.info("Device reactivated: id=%s user_id=%s", existing["id"], user_id)
