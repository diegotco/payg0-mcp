"""
Tests del servidor MCP de Payg0.

No llaman a la red: el API de Payg0 se simula con httpx.MockTransport.
"""
import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from payg0_mcp import client
from payg0_mcp.server import mcp

VALID_KEY = "pyg0_test_abc123"


# ─── Resolución de la API key ─────────────────────────────────────────────────

def test_key_from_x_api_key_header():
    assert client.resolve_api_key({"X-API-Key": VALID_KEY}) == VALID_KEY


def test_key_from_bearer_header():
    assert client.resolve_api_key({"Authorization": f"Bearer {VALID_KEY}"}) == VALID_KEY


def test_header_lookup_is_case_insensitive():
    assert client.resolve_api_key({"x-api-key": VALID_KEY}) == VALID_KEY


def test_key_from_env_on_stdio(monkeypatch):
    """En stdio no hay headers: la key viene de PAYG0_API_KEY."""
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)
    assert client.resolve_api_key(None) == VALID_KEY


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.delenv("PAYG0_API_KEY", raising=False)
    with pytest.raises(ToolError, match="Falta la API key"):
        client.resolve_api_key({})


def test_wrong_prefix_is_rejected():
    with pytest.raises(ToolError, match="formato esperado"):
        client.resolve_api_key({"X-API-Key": "sk_live_abc"})


# ─── Llamadas al API de Payg0 (simulado) ──────────────────────────────────────

@pytest.fixture
def payg0_api(monkeypatch):
    """Sustituye la red por un API de Payg0 simulado y registra cada request."""
    calls: list[httpx.Request] = []
    responses: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses.get(request.url.path, httpx.Response(404, json={"detail": "Not found"}))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return calls, responses


async def test_request_forwards_key_as_header(payg0_api):
    calls, responses = payg0_api
    responses["/api/v1/wallet/balance"] = httpx.Response(200, json={"balance": "100.00"})

    result = await client.request("GET", "/wallet/balance", VALID_KEY)

    assert result == {"balance": "100.00"}
    assert calls[0].headers["X-API-Key"] == VALID_KEY
    # La key nunca debe viajar en la URL.
    assert VALID_KEY not in str(calls[0].url)


@pytest.mark.parametrize("status,expected", [
    (401, "inválida o fue revocada"),
    (429, "Demasiadas solicitudes"),
    (500, "no está disponible"),
    (503, "no está disponible"),
])
async def test_api_errors_become_clear_messages(payg0_api, status, expected):
    _, responses = payg0_api
    responses["/api/v1/wallet/balance"] = httpx.Response(status, json={"detail": "x"})

    with pytest.raises(ToolError, match=expected):
        await client.request("GET", "/wallet/balance", VALID_KEY)


async def test_none_params_are_not_sent(payg0_api):
    calls, responses = payg0_api
    responses["/api/v1/payments/history"] = httpx.Response(200, json={"transactions": []})

    await client.request("GET", "/payments/history", VALID_KEY, params={"status": None, "page": 1})

    assert "status" not in calls[0].url.params
    assert calls[0].url.params["page"] == "1"


# ─── Herramientas MCP ─────────────────────────────────────────────────────────

async def test_phase1_exposes_only_read_only_tools():
    """Guarda de regresión: la Fase 1 no puede exponer herramientas que muevan dinero."""
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools

    assert {t.name for t in tools} == {"get_balance", "get_history", "get_transaction", "lookup_user"}
    for tool in tools:
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name


@pytest.mark.parametrize("bad_id", [
    "../../admin/api/users",
    "../wallet/balance",
    "not-a-uuid",
    "",
])
async def test_transaction_id_cannot_alter_the_path(payg0_api, monkeypatch, bad_id):
    """Un ID malicioso se rechaza antes de llegar a Payg0."""
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("get_transaction", {"transaction_id": bad_id})

    assert result.is_error
    assert calls == []


async def test_get_history_rejects_out_of_range_limit(payg0_api, monkeypatch):
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("get_history", {"limit": 500})

    assert result.is_error
    assert calls == []
