"""
Invoices API - Returns customer invoices from MariaDB.

Security flow:
1. Validate JWT → get user_id (sub claim)
2. Fetch customer_profile from Supabase → get erp_clt_prov
3. Query MariaDB with erp_clt_prov (NEVER from client)
"""
from datetime import date
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..core.auth import get_current_user, User
from ..core.supabase_admin import fetch_customer_profile, SupabaseUnavailableError
from ..repositories.invoice_repository import list_invoices

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invoices"])


class Invoice(BaseModel):
    factura: str
    fecha: date
    base_imponible: float
    importe_iva: float
    importe_total: float


@router.get("/invoices", response_model=list[Invoice])
async def get_invoices(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> list[Invoice]:
    """
    Get invoices for the authenticated customer.

    - Requires valid Supabase JWT
    - Returns invoices for current and previous fiscal year
    - Client cannot specify clt_prov - it's resolved server-side from customer_profiles
    """
    user_id = current_user.sub

    # Step 1: Fetch customer profile from Supabase
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

    # Step 2: Calculate fiscal years
    today = date.today()
    ejercicio_actual = today.year
    ejercicio_anterior = ejercicio_actual - 1

    # Step 3: Fetch invoices from repository
    try:
        rows = await list_invoices(
            clt_prov=clt_prov,
            ejercicio_actual=ejercicio_actual,
            ejercicio_anterior=ejercicio_anterior,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error("Database error fetching invoices: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching invoices")

    return rows
