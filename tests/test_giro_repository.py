"""Tests for giro_repository - mocked, no real DB connection."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.repositories import giro_repository
from app.repositories.giro_repository import (
    fetch_giros_by_cta_contable,
    fetch_giros_window,
    GIROS_BY_CTA_SQL,
    GIROS_WINDOW_SQL,
)


FAKE_POOL = object()  # sentinel — just needs to be passed through

SAMPLE_ROWS = [
    {
        "cta_contable": "430000962",
        "num_efecto": "R001",
        "vencimiento": date(2026, 3, 1),
        "importe": 1500.00,
    },
    {
        "cta_contable": "430000962",
        "num_efecto": "S002",
        "vencimiento": date(2026, 3, 5),
        "importe": 750.50,
    },
]


@pytest.fixture
def mock_execute(monkeypatch):
    """Patch execute_query and get_pool_finan in the repository module."""
    mock_eq = AsyncMock(return_value=SAMPLE_ROWS)
    mock_pool = AsyncMock(return_value=FAKE_POOL)
    monkeypatch.setattr(giro_repository, "execute_query", mock_eq)
    monkeypatch.setattr(giro_repository, "get_pool_finan", mock_pool)
    return mock_eq


class TestFetchGirosByCta:
    """Tests for fetch_giros_by_cta_contable."""

    @pytest.mark.asyncio
    async def test_uses_finan_pool(self, mock_execute):
        """Must pass the finan pool explicitly to execute_query."""
        await fetch_giros_by_cta_contable("430000962", date(2026, 3, 1), date(2026, 3, 10))

        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        assert kwargs["pool"] is FAKE_POOL

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, mock_execute):
        """Params dict must contain cta_contable, from_date, to_date."""
        await fetch_giros_by_cta_contable("430000962", date(2026, 3, 1), date(2026, 3, 10))

        call_args = mock_execute.call_args
        params = call_args[0][1]  # second positional arg
        assert params["cta_contable"] == "430000962"
        assert params["from_date"] == date(2026, 3, 1)
        assert params["to_date"] == date(2026, 3, 10)

    @pytest.mark.asyncio
    async def test_uses_correct_sql(self, mock_execute):
        """Must use the GIROS_BY_CTA_SQL query."""
        await fetch_giros_by_cta_contable("430000962", date(2026, 3, 1), date(2026, 3, 10))

        sql_used = mock_execute.call_args[0][0]
        assert sql_used is GIROS_BY_CTA_SQL

    @pytest.mark.asyncio
    async def test_returns_rows_unchanged(self, mock_execute):
        """Returns exactly what execute_query returns (no transformation)."""
        result = await fetch_giros_by_cta_contable("430000962", date(2026, 3, 1), date(2026, 3, 10))

        assert result == SAMPLE_ROWS
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self, monkeypatch):
        """Returns empty list when no giros found."""
        monkeypatch.setattr(giro_repository, "execute_query", AsyncMock(return_value=[]))
        monkeypatch.setattr(giro_repository, "get_pool_finan", AsyncMock(return_value=FAKE_POOL))

        result = await fetch_giros_by_cta_contable("999999999", date(2026, 3, 1), date(2026, 3, 10))
        assert result == []


class TestFetchGirosWindow:
    """Tests for fetch_giros_window."""

    @pytest.mark.asyncio
    async def test_uses_finan_pool(self, mock_execute):
        """Must pass the finan pool explicitly."""
        await fetch_giros_window(date(2026, 3, 1), date(2026, 3, 10))

        _, kwargs = mock_execute.call_args
        assert kwargs["pool"] is FAKE_POOL

    @pytest.mark.asyncio
    async def test_uses_window_sql(self, mock_execute):
        """Must use GIROS_WINDOW_SQL (no cta_contable filter)."""
        await fetch_giros_window(date(2026, 3, 1), date(2026, 3, 10))

        sql_used = mock_execute.call_args[0][0]
        assert sql_used is GIROS_WINDOW_SQL

    @pytest.mark.asyncio
    async def test_params_no_cta_contable(self, mock_execute):
        """Window query should NOT include cta_contable in params."""
        await fetch_giros_window(date(2026, 3, 1), date(2026, 3, 10))

        params = mock_execute.call_args[0][1]
        assert "cta_contable" not in params
        assert params["from_date"] == date(2026, 3, 1)
        assert params["to_date"] == date(2026, 3, 10)


class TestSqlContent:
    """Verify SQL queries contain the expected fixed filters."""

    def test_empresa_filter(self):
        assert "empresa    = 1" in GIROS_BY_CTA_SQL
        assert "empresa    = 1" in GIROS_WINDOW_SQL

    def test_giro_rec_filter(self):
        assert "giro_rec   = 0" in GIROS_BY_CTA_SQL

    def test_cobro_pago_filter(self):
        assert "cobro_pago = 1" in GIROS_BY_CTA_SQL

    def test_num_efecto_like_filter(self):
        assert "num_efecto LIKE 'R%%'" in GIROS_BY_CTA_SQL
        assert "num_efecto LIKE 'S%%'" in GIROS_BY_CTA_SQL

    def test_order_by(self):
        assert "ORDER BY vencimiento ASC, num_efecto ASC" in GIROS_BY_CTA_SQL

    def test_by_cta_has_cli_pro_filter(self):
        assert "cli_pro = %(cta_contable)s" in GIROS_BY_CTA_SQL

    def test_window_has_no_cli_pro_filter(self):
        assert "cli_pro" not in GIROS_WINDOW_SQL.split("WHERE")[1].split("ORDER")[0]
