"""
Invoice PDF download - Streams PDF from NAS/local filesystem.

Security: reuses the same auth + customer profile flow as /invoices.
The client never sees internal paths.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..core.auth import get_current_user, User
from ..core.config import settings
from ..core.supabase_admin import fetch_customer_profile, SupabaseUnavailableError
from ..repositories.invoice_repository import check_invoice_ownership
from .invoices import decode_invoice_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])


@router.get("/invoices/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Download the PDF for a specific invoice.

    - 400: invalid invoice_id
    - 401: missing/invalid JWT (handled by auth dependency)
    - 403: invoice belongs to another customer
    - 404: invoice not found in database
    - 409: invoice exists but PDF file not generated yet
    - 503: upstream profile service unavailable
    """
    # --- Decode invoice_id ---
    try:
        fields = decode_invoice_id(invoice_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invoice_id")

    # --- Resolve customer profile (same as /invoices) ---
    try:
        profile = await fetch_customer_profile(current_user.sub)
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Upstream auth/profile service unavailable")

    if profile is None:
        raise HTTPException(status_code=403, detail="No customer profile found")
    if not profile.is_active:
        raise HTTPException(status_code=403, detail="Customer profile is not active")

    clt_prov = profile.erp_clt_prov

    # --- Check ownership in DB ---
    try:
        owner = await check_invoice_ownership(
            ejercicio=fields["ejercicio"],
            clave=fields["clave"],
            documento=fields["documento"],
            serie=fields["serie"],
            numero=fields["numero"],
        )
    except Exception:
        logger.error("Database error checking invoice ownership")
        raise HTTPException(status_code=500, detail="Error checking invoice")

    if owner is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Strip/normalize for safe comparison
    if str(owner).strip() != str(clt_prov).strip():
        raise HTTPException(status_code=403, detail="Invoice does not belong to customer")

    # --- Build file path (never from client input) ---
    filename = f"Factura_{fields['documento']}{fields['numero']}.pdf"
    pdf_path = (
        Path(settings.pdf_base_dir)
        / fields["ejercicio"]
        / str(clt_prov).strip()
        / filename
    )

    if not pdf_path.is_file():
        raise HTTPException(status_code=409, detail="Invoice PDF not generated yet")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
