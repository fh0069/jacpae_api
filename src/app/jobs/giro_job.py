"""
Daily giro notification job.

Reads active customer profiles from Supabase, queries upcoming giros
from MariaDB contabilidad (g4finan), and inserts deduplicated
notifications into Supabase.
"""
import logging
from datetime import date, timedelta
from typing import Any

from ..core.config import settings
from ..core.supabase_admin import (
    CustomerProfileGiro,
    NotificationInsert,
    SupabaseUnavailableError,
    fetch_giro_profiles,
    insert_notification,
)
from ..repositories.giro_repository import fetch_giros_by_cta_contable

logger = logging.getLogger(__name__)


def _build_notification(
    profile: CustomerProfileGiro,
    giro: dict[str, Any],
) -> NotificationInsert:
    """Build a NotificationInsert from a profile + giro row."""
    vencimiento: date = giro["vencimiento"]
    importe = giro["importe"]
    num_efecto = giro["num_efecto"]
    cta_contable = giro["cta_contable"]

    return NotificationInsert(
        user_id=profile.user_id,
        type="giro",
        title="Giro pendiente",
        body=(
            f"El efecto {num_efecto} por importe de {importe:.2f} \u20ac "
            f"vence el {vencimiento:%d/%m/%Y}."
        ),
        event_date=vencimiento,
        data={
            "cta_contable": cta_contable,
            "num_efecto": num_efecto,
            "vencimiento": vencimiento.isoformat(),
            "importe": float(importe),
        },
        source_key=f"giro:{cta_contable}:{num_efecto}:{vencimiento.isoformat()}",
    )


async def run_giro_job() -> dict[str, int]:
    """
    Main entry point for the daily giro notification job.

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
        profiles = await fetch_giro_profiles()
    except SupabaseUnavailableError:
        logger.error("Giro job aborted: cannot fetch profiles from Supabase")
        summary["errors"] = 1
        return summary

    summary["total_profiles"] = len(profiles)

    if not profiles:
        logger.info("Giro job: no active profiles with avisar_giro=true")
        return summary

    today = date.today()

    for profile in profiles:
        dias = profile.dias_aviso_giro or settings.giro_default_dias_aviso
        from_date = today
        to_date = today + timedelta(days=dias)

        logger.debug(
            "Giro job: profile user_id=%s cta=%s window=[%s, %s]",
            profile.user_id, profile.cta_contable, from_date, to_date,
        )

        try:
            giros = await fetch_giros_by_cta_contable(
                profile.cta_contable, from_date, to_date,
            )
        except Exception:
            logger.exception(
                "Giro job: error querying giros for cta=%s", profile.cta_contable,
            )
            summary["errors"] += 1
            continue

        summary["total_rows"] += len(giros)

        for giro in giros:
            notification = _build_notification(profile, giro)
            try:
                was_inserted = await insert_notification(notification)
                if was_inserted:
                    summary["inserted"] += 1
                else:
                    summary["deduped"] += 1
            except SupabaseUnavailableError:
                logger.error(
                    "Giro job: Supabase unavailable inserting source_key=%s",
                    notification.source_key,
                )
                summary["errors"] += 1

    logger.info(
        "Giro job completed: profiles=%d rows=%d inserted=%d deduped=%d errors=%d",
        summary["total_profiles"],
        summary["total_rows"],
        summary["inserted"],
        summary["deduped"],
        summary["errors"],
    )
    return summary
