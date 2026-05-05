"""
Finance API – Ledger/extracto del cliente.

Security flow (same as /invoices):
1. Validate JWT → get user_id (sub claim)
2. Fetch customer_profile from Supabase → get cta_contable
3. Query MARIADB_FINAN_DB via service/repository (NEVER expose cta_contable to client)
"""
import asyncio
import logging
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
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


# ── Excel helper ───────────────────────────────────────────────

def _build_xlsx(data: dict) -> BytesIO:
    # ── Style constants ──────────────────────────────────────────
    _THIN = Side(style="thin")
    _FULL_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

    _HDR_FILL = PatternFill("solid", fgColor="F28C28")
    _HDR_FONT = Font(bold=True, color="FFFFFF")

    _CENTER = Alignment(horizontal="center", vertical="center")
    _LEFT   = Alignment(horizontal="left",   vertical="center")
    _RIGHT  = Alignment(horizontal="right",  vertical="center")

    FMT_CURRENCY = '#,##0.00 €'
    FMT_DATE     = 'DD-MM-YYYY'

    # (visible header, field, col width, number format, alignment)
    COLUMNS = [
        ("Fecha",    "fecha",         14, FMT_DATE,     _CENTER),
        ("Concepto", "concepto",      42, None,         _LEFT),
        ("Debe",     "importe_debe",  16, FMT_CURRENCY, _RIGHT),
        ("Haber",    "importe_haber", 16, FMT_CURRENCY, _RIGHT),
        ("Saldo",    "saldo",         16, FMT_CURRENCY, _RIGHT),
    ]
    _NUMERIC = {"importe_debe", "importe_haber", "saldo"}

    wb = Workbook()
    ws = wb.active
    ws.title = "Extracto"

    # ── Header row ───────────────────────────────────────────────
    ws.append([col[0] for col in COLUMNS])
    ws.row_dimensions[1].height = 22
    for col_idx, cell in enumerate(ws[1], start=1):
        cell.font = _HDR_FONT
        cell.fill = _HDR_FILL
        cell.alignment = _CENTER
        cell.border = _FULL_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = COLUMNS[col_idx - 1][2]

    # ── Data rows ────────────────────────────────────────────────
    for item in data["items"]:
        row_idx = ws.max_row + 1
        ws.append([
            float(item[col[1]]) if col[1] in _NUMERIC else item[col[1]]
            for col in COLUMNS
        ])
        for col_idx, col in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if col[3]:
                cell.number_format = col[3]
            cell.alignment = col[4]

    # ── Autofilter + freeze pane ─────────────────────────────────
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{ws.max_row}"
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── Export endpoint ────────────────────────────────────────────

@router.get("/finance/ledger/export")
async def export_finance_ledger(
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
        data = await get_ledger(
            cta_contable=profile.cta_contable,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error("Database error fetching ledger for export: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Error fetching ledger")

    buf = await asyncio.to_thread(_build_xlsx, data)

    filename = f"ledger_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
