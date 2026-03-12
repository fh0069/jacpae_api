"""
Finance API – Ledger/extracto del cliente.

Security flow (same as /invoices):
1. Validate JWT → get user_id (sub claim)
2. Fetch customer_profile from Supabase → get cta_contable
3. Query MARIADB_FINAN_DB via service/repository (NEVER expose cta_contable to client)
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..core.auth import get_current_user, User
from ..core.date_utils import validate_date_range
from ..core.supabase_admin import fetch_customer_profile, SupabaseUnavailableError
from ..services.finance_service import get_ledger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["finance"])


# ── Schemas ────────────────────────────────────────────────────

class LedgerItem(BaseModel):
    fecha: date
    concepto: str
    importe_debe: float
    importe_haber: float
    saldo: float


class LedgerResponse(BaseModel):
    start_date: date
    end_date: date
    exercise_start_date: date
    total_items: int
    items: list[LedgerItem]


# ── Endpoint ───────────────────────────────────────────────────

@router.get("/finance/ledger", response_model=LedgerResponse)
async def get_finance_ledger(
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
) -> LedgerResponse:
    """
    Get the account ledger (extracto/mayor) for the authenticated customer.

    - Requires valid Supabase JWT
    - start_date and end_date define the visible range of movements
    - Opening balance is calculated from the start of start_date's fiscal year (service layer)
    - Client cannot specify cta_contable – resolved server-side from customer_profiles
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
        result = await get_ledger(
            cta_contable=profile.cta_contable,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error("Database error fetching ledger: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching ledger")

    return result
