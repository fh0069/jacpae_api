"""
Daily reparto notification job.

Reads active customer profiles from Supabase, calculates business-day
target dates, queries scheduled routes from MariaDB gestión (g4),
and inserts deduplicated notifications into Supabase.
"""
import logging
from datetime import date, timedelta
from typing import Any

from ..core.config import settings
from ..core.supabase_admin import (
    CustomerProfileReparto,
    NotificationInsert,
    SupabaseUnavailableError,
    fetch_reparto_profiles,
    insert_notification,
)
from ..repositories.reparto_repository import fetch_repartos_by_client

logger = logging.getLogger(__name__)


def add_business_days(start_date: date, n: int) -> date:
    """
    Add *n* business days (Mon–Fri) to *start_date*.

    No public-holiday calendar — only skips weekends.

    Args:
        start_date: Base date.
        n: Number of business days to add (>= 0).

    Returns:
        The resulting date after advancing n business days.
    """
    if n < 0:
        raise ValueError("n must be >= 0")

    current = start_date
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        # Monday=0 … Friday=4 → weekday
        if current.weekday() < 5:
            remaining -= 1
    return current


def _build_notification(
    profile: CustomerProfileReparto,
    row: dict[str, Any],
    target_date: date,
) -> NotificationInsert:
    """Build a NotificationInsert from a profile + route row."""
    clt_prov = row["clt_prov"]
    ruta = row["ruta"]
    subruta = row["subruta"]

    return NotificationInsert(
        user_id=profile.user_id,
        type="reparto",
        title="🚚 Reparto programado",
        body=(
            f"Cargamos para su zona el {target_date:%d/%m/%Y}.\n"
            f"Realice su pedido antes de las 23:59 del día anterior."
        ),
        event_date=target_date,
        data={
            "clt_prov": clt_prov,
            "fecha": target_date.isoformat(),
            "ruta": ruta,
            "subruta": subruta,
            "grupo": row["grupo"],
            "subgrupo": row["subgrupo"],
        },
        source_key=f"reparto:{clt_prov}:{ruta}:{subruta}:{target_date.isoformat()}",
    )


async def run_reparto_job() -> dict[str, int]:
    """
    Main entry point for the daily reparto notification job.

    Returns:
        Summary dict with keys: total_profiles, total_rows, inserted, deduped, errors
    """
    summary: dict[str, int] = {
        "total_profiles": 0,
        "total_rows": 0,
        "inserted": 0,
        "deduped": 0,
        "errors": 0,
    }

    try:
        profiles = await fetch_reparto_profiles()
    except SupabaseUnavailableError:
        logger.error("Reparto job aborted: cannot fetch profiles from Supabase")
        summary["errors"] = 1
        return summary

    summary["total_profiles"] = len(profiles)

    if not profiles:
        logger.info("Reparto job: no active profiles with avisar_reparto=true")
        return summary

    today = date.today()

    for profile in profiles:
        dias = profile.dias_aviso_reparto or settings.reparto_default_dias_aviso
        target_date = add_business_days(today, dias)

        logger.debug(
            "Reparto job: profile user_id=%s clt_prov=%s target_date=%s",
            profile.user_id, profile.erp_clt_prov, target_date,
        )

        try:
            repartos = await fetch_repartos_by_client(
                profile.erp_clt_prov, target_date,
            )
        except Exception:
            logger.exception(
                "Reparto job: error querying repartos for clt_prov=%s",
                profile.erp_clt_prov,
            )
            summary["errors"] += 1
            continue

        summary["total_rows"] += len(repartos)

        for row in repartos:
            notification = _build_notification(profile, row, target_date)
            try:
                was_inserted = await insert_notification(notification)
                if was_inserted:
                    summary["inserted"] += 1
                else:
                    summary["deduped"] += 1
            except SupabaseUnavailableError:
                logger.error(
                    "Reparto job: Supabase unavailable inserting source_key=%s",
                    notification.source_key,
                )
                summary["errors"] += 1

    logger.info(
        "Reparto job completed: profiles=%d rows=%d inserted=%d deduped=%d errors=%d",
        summary["total_profiles"],
        summary["total_rows"],
        summary["inserted"],
        summary["deduped"],
        summary["errors"],
    )
    return summary
