"""
Daily invoice notification job.

Reads active customer profiles from Supabase, queries recently issued
invoices from MARIADB_DB within a 5-day lookback window, and inserts
deduplicated notifications into Supabase.

After inserting at least one new notification for a user, dispatches a
single FCM push via send_push_to_user() as a wake-up signal. A push
failure never affects the notification persistence flow.
"""
import logging
from datetime import date, timedelta
from typing import Any

from ..core.supabase_admin import (
    CustomerProfileInvoice,
    NotificationInsert,
    SupabaseUnavailableError,
    fetch_invoice_profiles,
    insert_notification,
)
from ..repositories.invoice_repository import fetch_invoices_by_clt_prov
from ..services.fcm_service import send_push_to_user

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 5


def _build_notification(
    profile: CustomerProfileInvoice,
    invoice: dict[str, Any],
) -> NotificationInsert:
    """Build a NotificationInsert from a profile + invoice row."""
    ejercicio = invoice["ejercicio_factura"]
    clave = invoice["clave_factura"]
    documento = invoice["documento_factura"]
    serie = invoice["serie_factura"]
    numero = invoice["numero_factura"]
    fecha: date = invoice["fecha"]

    return NotificationInsert(
        user_id=profile.user_id,
        type="factura_emitida",
        title="Nueva factura disponible",
        body="Ya puedes consultar una nueva factura emitida en la app.",
        event_date=fecha,
        data={},
        source_key=f"factura_emitida:{ejercicio}:{clave}:{documento}:{serie}:{numero}",
    )


async def run_invoice_job() -> dict[str, int]:
    """
    Main entry point for the daily invoice notification job.

    Returns:
        Summary dict with keys:
          total_profiles, inserted, deduped, errors,
          push_sent, push_failed, push_invalidated
    """
    summary: dict[str, int] = {
        "total_profiles": 0,
        "inserted": 0,
        "deduped": 0,
        "errors": 0,
        "push_sent": 0,
        "push_failed": 0,
        "push_invalidated": 0,
    }

    try:
        profiles = await fetch_invoice_profiles()
    except SupabaseUnavailableError:
        logger.error("Invoice job aborted: cannot fetch profiles from Supabase")
        summary["errors"] = 1
        return summary

    summary["total_profiles"] = len(profiles)

    if not profiles:
        logger.info("Invoice job: no active profiles with avisar_factura_emitida=true")
        return summary

    today = date.today()
    from_date = today - timedelta(days=_LOOKBACK_DAYS)
    to_date = today

    for profile in profiles:
        logger.debug(
            "Invoice job: profile user_id=%s clt_prov=%s window=[%s, %s]",
            profile.user_id, profile.erp_clt_prov, from_date, to_date,
        )

        try:
            invoices = await fetch_invoices_by_clt_prov(
                profile.erp_clt_prov, from_date, to_date,
            )
        except Exception:
            logger.exception(
                "Invoice job: error querying invoices for clt_prov=%s",
                profile.erp_clt_prov,
            )
            summary["errors"] += 1
            continue

        user_had_new = False

        for invoice in invoices:
            notification = _build_notification(profile, invoice)
            try:
                was_inserted = await insert_notification(notification)
                if was_inserted:
                    summary["inserted"] += 1
                    user_had_new = True
                else:
                    summary["deduped"] += 1
            except SupabaseUnavailableError:
                logger.error(
                    "Invoice job: Supabase unavailable inserting source_key=%s",
                    notification.source_key,
                )
                summary["errors"] += 1

        if user_had_new:
            push_result = await send_push_to_user(
                user_id=profile.user_id,
                title="Tienes notificaciones nuevas",
                body="",
                data={"type": "factura_emitida"},
            )
            summary["push_sent"] += push_result.sent
            summary["push_failed"] += push_result.failed
            summary["push_invalidated"] += push_result.invalidated

    logger.info(
        "Invoice job completed: profiles=%d inserted=%d deduped=%d errors=%d "
        "push_sent=%d push_failed=%d push_invalidated=%d",
        summary["total_profiles"],
        summary["inserted"],
        summary["deduped"],
        summary["errors"],
        summary["push_sent"],
        summary["push_failed"],
        summary["push_invalidated"],
    )
    return summary
