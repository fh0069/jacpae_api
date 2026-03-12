"""
Invoice Reporting API – VAT invoice list (listado fiscal de facturas).

Security flow (same as /invoices):
1. Validate JWT → get user_id (sub claim)
2. Fetch customer_profile from Supabase → get erp_clt_prov
3. Query MariaDB via service/repository (NEVER expose clt_prov to client)

Note: This router is intentionally separate from api/invoices.py to avoid
modifying the existing /invoices endpoint.
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..core.auth import get_current_user, User
from ..core.date_utils import validate_date_range
from ..core.supabase_admin import fetch_customer_profile, SupabaseUnavailableError
from ..services.invoice_reporting_service import get_vat_invoice_list

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])


# ── Schemas ────────────────────────────────────────────────────

class VatInvoiceItem(BaseModel):
    num_fra: str
    fecha_fra: date
    base_imp: float
    iva: float
    imp_total: float


class VatTotals(BaseModel):
    total_base_imp: float
    total_iva: float
    total_imp_total: float


class VatInvoiceListResponse(BaseModel):
    start_date: date
    end_date: date
    total_items: int
    items: list[VatInvoiceItem]
    totals: Optional[VatTotals] = None


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
    - Client cannot specify clt_prov – resolved server-side from customer_profiles
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

    clt_prov = profile.erp_clt_prov

    try:
        result = await get_vat_invoice_list(
            clt_prov=clt_prov,
            start_date=start_date,
            end_date=end_date,
        )
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="VAT invoice list query not yet implemented")
    except Exception as e:
        logger.error("Database error fetching VAT invoice list: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching VAT invoice list")

    return result
