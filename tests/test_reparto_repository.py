"""Tests for reparto_repository — mocked, no real DB connection."""
import pytest
from datetime import date
from unittest.mock import AsyncMock

from app.repositories import reparto_repository
from app.repositories.reparto_repository import (
    fetch_repartos_by_client,
    REPARTOS_BY_CLIENT_SQL,
)


FAKE_POOL = object()  # sentinel — just needs to be passed through

SAMPLE_ROWS = [
    {
        "clt_prov": "000962",
        "fecha": date(2026, 2, 19),
        "ruta": 1,
        "subruta": 0,
        "grupo": 10,
        "subgrupo": 1,
    },
    {
        "clt_prov": "000962",
        "fecha": date(2026, 2, 19),
        "ruta": 2,
        "subruta": 1,
        "grupo": 10,
        "subgrupo": 1,
    },
]


@pytest.fixture
def mock_execute(monkeypatch):
    """Patch execute_query and get_pool in the repository module."""
    mock_eq = AsyncMock(return_value=SAMPLE_ROWS)
    mock_pool = AsyncMock(return_value=FAKE_POOL)
    monkeypatch.setattr(reparto_repository, "execute_query", mock_eq)
    monkeypatch.setattr(reparto_repository, "get_pool", mock_pool)
    return mock_eq


class TestFetchRepartosByClient:
    """Tests for fetch_repartos_by_client."""

    @pytest.mark.asyncio
    async def test_uses_ventas_pool(self, mock_execute):
        """Must pass the ventas (default) pool explicitly to execute_query."""
        await fetch_repartos_by_client("000962", date(2026, 2, 19))

        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        assert kwargs["pool"] is FAKE_POOL

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, mock_execute):
        """Params dict must contain clt_prov and target_date."""
        await fetch_repartos_by_client("000962", date(2026, 2, 19))

        call_args = mock_execute.call_args
        params = call_args[0][1]  # second positional arg
        assert params["clt_prov"] == "000962"
        assert params["target_date"] == date(2026, 2, 19)

    @pytest.mark.asyncio
    async def test_uses_correct_sql(self, mock_execute):
        """Must use the REPARTOS_BY_CLIENT_SQL query."""
        await fetch_repartos_by_client("000962", date(2026, 2, 19))

        sql_used = mock_execute.call_args[0][0]
        assert sql_used is REPARTOS_BY_CLIENT_SQL

    @pytest.mark.asyncio
    async def test_returns_rows_unchanged(self, mock_execute):
        """Returns exactly what execute_query returns (no transformation)."""
        result = await fetch_repartos_by_client("000962", date(2026, 2, 19))

        assert result == SAMPLE_ROWS
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self, monkeypatch):
        """Returns empty list when no routes found."""
        monkeypatch.setattr(reparto_repository, "execute_query", AsyncMock(return_value=[]))
        monkeypatch.setattr(reparto_repository, "get_pool", AsyncMock(return_value=FAKE_POOL))

        result = await fetch_repartos_by_client("999999", date(2026, 2, 19))
        assert result == []


class TestSqlContent:
    """Verify SQL query contains the expected filters and structure."""

    def test_baja_comercial_filter(self):
        assert "baja_comercial = 'N'" in REPARTOS_BY_CLIENT_SQL

    def test_clt_prov_param(self):
        assert "c.codigo = %(clt_prov)s" in REPARTOS_BY_CLIENT_SQL

    def test_target_date_param(self):
        assert "r.fecha  = %(target_date)s" in REPARTOS_BY_CLIENT_SQL

    def test_join_lin_rutas_grupo(self):
        assert "INNER JOIN lin_rutas_grupo l" in REPARTOS_BY_CLIENT_SQL

    def test_join_rutas_programacion(self):
        assert "INNER JOIN rutas_programacion r" in REPARTOS_BY_CLIENT_SQL

    def test_order_by_stable(self):
        assert "ORDER BY r.fecha ASC, c.codigo ASC, l.ruta ASC, l.subruta ASC" in REPARTOS_BY_CLIENT_SQL

    def test_select_includes_ruta_subruta(self):
        """SELECT must include ruta/subruta for source_key uniqueness."""
        assert "l.ruta" in REPARTOS_BY_CLIENT_SQL
        assert "l.subruta" in REPARTOS_BY_CLIENT_SQL

    def test_select_includes_grupo_subgrupo(self):
        """SELECT must include grupo/subgrupo for data enrichment."""
        assert "l.grupo" in REPARTOS_BY_CLIENT_SQL
        assert "l.subgrupo" in REPARTOS_BY_CLIENT_SQL
