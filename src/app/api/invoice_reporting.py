"""
Invoice Reporting API – VAT invoice list (listado fiscal de facturas).

Security flow (same as /finance/ledger):
1. Validate JWT → get user_id (sub claim)
2. Fetch customer_profile from Supabase → get cta_contable
3. Query MARIADB_FINAN_DB via service/repository (NEVER expose cta_contable to client)

Note: This router is intentionally separate from api/invoices.py to avoid
modifying the existing /invoices endpoint.
"""
import asyncio
import logging
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from ..core.auth import get_current_user, User
from ..core.date_utils import validate_date_range
from ..core.supabase_admin import fetch_customer_profile, SupabaseUnavailableError
from ..services.invoice_reporting_service import get_vat_invoice_list

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])


# ── Schemas ────────────────────────────────────────────────────

class VatInvoiceItem(BaseModel):
    fecha_fra: date
    num_fra: str
    base_imp: float
    tipo_iva: float
    cuota_iva: float
    tipo_recargo: float
    cuota_recargo: float
    imp_total: float


class VatInvoiceTotals(BaseModel):
    total_base: float
    total_iva: float
    total_recargo: float
    total_factura: float


class VatInvoiceListResponse(BaseModel):
    items: list[VatInvoiceItem]
    totals: VatInvoiceTotals


# ── Endpoint ───────────────────────────────────────────────────

@router.get("/invoices/vat-list", response_model=VatInvoiceListResponse)
async def get_vat_invoice_list_endpoint(
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
) -> VatInvoiceListResponse:
    """
    Get the VAT invoice list (listado fiscal) for the authenticated customer.

    - Requires valid Supabase JWT
    - Both start_date and end_date are required
    - Client cannot specify cta_contable – resolved server-side from customer_profiles
    - Includes aggregated period totals (base, IVA, recargo, total)
    """
    try:
        validate_date_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user_id = current_user.sub

    try:
        profile = await fetch_customer_profile(user_id)
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Upstream auth/profile service unavailable")

    if profile is None:
        logger.warning("No customer_profile found for user_id=%s", user_id)
        raise HTTPException(status_code=403, detail="No customer profile found")

    if not profile.is_active:
        logger.warning("Customer profile is_active=false for user_id=%s", user_id)
        raise HTTPException(status_code=403, detail="Customer profile is not active")

    if not profile.cta_contable:
        logger.warning("Customer profile has no cta_contable for user_id=%s", user_id)
        raise HTTPException(status_code=403, detail="Customer profile has no accounting account configured")

    try:
        result = await get_vat_invoice_list(
            cta_contable=profile.cta_contable,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error("Database error fetching VAT invoice list: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching VAT invoice list")

    return result


# ── Excel helper ───────────────────────────────────────────────

_ITEM_COLUMNS = [
    "fecha_fra",
    "num_fra",
    "base_imp",
    "tipo_iva",
    "cuota_iva",
    "tipo_recargo",
    "cuota_recargo",
    "imp_total",
]

_TOTALS_LABELS = [
    ("total_base", "Total Base"),
    ("total_iva", "Total IVA"),
    ("total_recargo", "Total Recargo"),
    ("total_factura", "Total Factura"),
]


def _build_xlsx(data: dict) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Facturas"

    ws.append(_ITEM_COLUMNS)

    _NUMERIC = {"base_imp", "tipo_iva", "cuota_iva", "tipo_recargo", "cuota_recargo", "imp_total"}
    for item in data["items"]:
        ws.append([
            float(item[col]) if col in _NUMERIC else item[col]
            for col in _ITEM_COLUMNS
        ])

    ws.append([])

    totals = data["totals"]
    for key, label in _TOTALS_LABELS:
        ws.append([label, float(totals[key])])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── Export endpoint ────────────────────────────────────────────

@router.get("/invoices/vat-list/export")
async def export_vat_invoice_list(
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    try:
        validate_date_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user_id = current_user.sub

    try:
        profile = await fetch_customer_profile(user_id)
    except SupabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Upstream auth/profile service unavailable")

    if profile is None:
        raise HTTPException(status_code=403, detail="No customer profile found")

    if not profile.is_active:
        raise HTTPException(status_code=403, detail="Customer profile is not active")

    if not profile.cta_contable:
        raise HTTPException(status_code=403, detail="Customer profile has no accounting account configured")

    try:
        data = await get_vat_invoice_list(
            cta_contable=profile.cta_contable,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error("Database error fetching VAT invoice list for export: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching VAT invoice list")

    buf = await asyncio.to_thread(_build_xlsx, data)

    filename = f"vat_invoices_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
