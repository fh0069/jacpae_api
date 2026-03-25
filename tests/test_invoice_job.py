"""Tests for invoice_job — fully mocked, no real DB or Supabase."""
import pytest
from datetime import date
from unittest.mock import AsyncMock

import app.jobs.invoice_job as job_module
from app.jobs.invoice_job import run_invoice_job, _build_notification
from app.core.supabase_admin import (
    CustomerProfileInvoice,
    SupabaseUnavailableError,
)
from app.services.fcm_service import PushResult


# ── Helpers ───────────────────────────────────────────────────


def _make_profile(
    user_id: str = "uid-1",
    erp_clt_prov: str = "000962",
) -> CustomerProfileInvoice:
    return CustomerProfileInvoice(
        user_id=user_id,
        erp_clt_prov=erp_clt_prov,
    )


def _make_invoice(
    ejercicio: str = "2026",
    clave: str = "B",
    documento: str = "FA",
    serie: str = "",
    numero: str = "000123",
    fecha: date = date(2026, 3, 20),
) -> dict:
    return {
        "ejercicio_factura": ejercicio,
        "clave_factura": clave,
        "documento_factura": documento,
        "serie_factura": serie,
        "numero_factura": numero,
        "factura": f"{documento}-{numero}",
        "fecha": fecha,
    }


# ── _build_notification ───────────────────────────────────────


class TestBuildNotification:
    """Unit tests for the notification builder."""

    def test_all_fields(self):
        n = _build_notification(_make_profile(), _make_invoice())

        assert n.user_id == "uid-1"
        assert n.type == "factura_emitida"
        assert n.title == "Nueva factura disponible"
        assert n.body == "Ya puedes consultar una nueva factura emitida en la app."
        assert n.event_date == date(2026, 3, 20)

    def test_source_key_format(self):
        n = _build_notification(
            _make_profile(),
            _make_invoice(ejercicio="2026", clave="B", documento="FA", serie="", numero="000123"),
        )
        assert n.source_key == "factura_emitida:2026:B:FA::000123"

    def test_source_key_distinguishes_invoices(self):
        """Different invoice numbers produce different source_keys."""
        n1 = _build_notification(_make_profile(), _make_invoice(numero="000001"))
        n2 = _build_notification(_make_profile(), _make_invoice(numero="000002"))
        assert n1.source_key != n2.source_key

    def test_no_sensitive_data_in_payload(self):
        """Financial amounts must not appear in notification data."""
        n = _build_notification(_make_profile(), _make_invoice())
        sensitive = {"base_imponible", "importe_iva", "importe_total", "imp_base", "imp_iva", "imp_total"}
        assert not sensitive.intersection(n.data.keys())


# ── run_invoice_job ───────────────────────────────────────────


class TestRunInvoiceJob:
    """Integration tests for the main job function (all dependencies mocked)."""

    @pytest.mark.asyncio
    async def test_no_profiles(self, monkeypatch):
        """No eligible profiles → all counters are 0."""
        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[]))

        result = await run_invoice_job()

        assert result["total_profiles"] == 0
        assert result["inserted"] == 0
        assert result["deduped"] == 0
        assert result["errors"] == 0
        assert result["push_sent"] == 0
        assert result["push_failed"] == 0
        assert result["push_invalidated"] == 0

    @pytest.mark.asyncio
    async def test_no_invoices_for_profile(self, monkeypatch):
        """Profile with no invoices in window → no insert, no push."""
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[]))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["inserted"] == 0
        assert result["errors"] == 0
        mock_push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_invoice_inserted_triggers_push(self, monkeypatch):
        """1 profile, 1 new invoice → inserted=1, push called once."""
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["inserted"] == 1
        assert result["deduped"] == 0
        assert result["errors"] == 0
        mock_push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invoice_deduped_no_push(self, monkeypatch):
        """Invoice already notified → deduped=1, push not called."""
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=False))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["deduped"] == 1
        assert result["inserted"] == 0
        mock_push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_two_invoices_one_push(self, monkeypatch):
        """1 profile, 2 new invoices → inserted=2, push called exactly once."""
        invoices = [_make_invoice(numero="000001"), _make_invoice(numero="000002")]
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=invoices))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["inserted"] == 2
        mock_push.assert_awaited_once()  # per-user, not per-invoice

    @pytest.mark.asyncio
    async def test_two_profiles_two_push(self, monkeypatch):
        """2 profiles, 1 invoice each → push called twice."""
        profiles = [
            _make_profile(user_id="uid-1", erp_clt_prov="000962"),
            _make_profile(user_id="uid-2", erp_clt_prov="000963"),
        ]
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        await run_invoice_job()

        assert mock_push.await_count == 2

    @pytest.mark.asyncio
    async def test_push_called_with_correct_args(self, monkeypatch):
        """send_push_to_user called with data={"type": "factura_emitida"}."""
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(
            job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile(user_id="uid-42")])
        )
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        await run_invoice_job()

        mock_push.assert_awaited_once_with(
            user_id="uid-42",
            title="Tienes notificaciones nuevas",
            body="",
            data={"type": "factura_emitida"},
        )

    @pytest.mark.asyncio
    async def test_push_failed_does_not_increment_errors(self, monkeypatch):
        """push_failed is independent from the errors counter."""
        push_result = PushResult(tokens_queried=1, sent=0, failed=1, invalidated=0)

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", AsyncMock(return_value=push_result))

        result = await run_invoice_job()

        assert result["errors"] == 0
        assert result["push_failed"] == 1
        assert result["inserted"] == 1

    @pytest.mark.asyncio
    async def test_push_invalidated_separate_from_failed(self, monkeypatch):
        """push_invalidated and push_failed accumulate independently."""
        push_result = PushResult(tokens_queried=2, sent=0, failed=1, invalidated=1)

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", AsyncMock(return_value=push_result))

        result = await run_invoice_job()

        assert result["push_failed"] == 1
        assert result["push_invalidated"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_profiles(self, monkeypatch):
        """SupabaseUnavailableError on fetch_profiles → errors=1, no crash."""
        monkeypatch.setattr(
            job_module,
            "fetch_invoice_profiles",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )

        result = await run_invoice_job()

        assert result["errors"] == 1
        assert result["total_profiles"] == 0

    @pytest.mark.asyncio
    async def test_mariadb_error_skips_profile(self, monkeypatch):
        """DB error on one profile → errors++, other profiles continue."""
        profiles = [
            _make_profile(user_id="uid-1", erp_clt_prov="000962"),
            _make_profile(user_id="uid-2", erp_clt_prov="000963"),
        ]
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=profiles))
        monkeypatch.setattr(
            job_module,
            "fetch_invoices_by_clt_prov",
            AsyncMock(side_effect=[Exception("DB down"), [_make_invoice()]]),
        )
        monkeypatch.setattr(job_module, "insert_notification", AsyncMock(return_value=True))
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["total_profiles"] == 2
        assert result["errors"] == 1
        assert result["inserted"] == 1
        mock_push.assert_awaited_once()  # uid-1 hits continue; uid-2 triggers push

    @pytest.mark.asyncio
    async def test_supabase_unavailable_on_insert(self, monkeypatch):
        """SupabaseUnavailableError on insert → errors++, push not called."""
        mock_push = AsyncMock(return_value=PushResult())

        monkeypatch.setattr(job_module, "fetch_invoice_profiles", AsyncMock(return_value=[_make_profile()]))
        monkeypatch.setattr(job_module, "fetch_invoices_by_clt_prov", AsyncMock(return_value=[_make_invoice()]))
        monkeypatch.setattr(
            job_module,
            "insert_notification",
            AsyncMock(side_effect=SupabaseUnavailableError("down")),
        )
        monkeypatch.setattr(job_module, "send_push_to_user", mock_push)

        result = await run_invoice_job()

        assert result["errors"] == 1
        assert result["inserted"] == 0
        mock_push.assert_not_awaited()
