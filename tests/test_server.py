"""
Tests del servidor MCP de Payg0.

No llaman a la red: el API de Payg0 se simula con httpx.MockTransport.
"""
import json

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

READ_ONLY_TOOLS = {"get_balance", "get_history", "get_transaction", "lookup_user", "validate_payment"}
WRITE_TOOLS = {"cancel_payment"}


async def test_every_tool_is_classified():
    """
    Guarda de regresión: cada herramienta debe estar clasificada aquí a
    propósito. Una herramienta nueva hace fallar este test hasta que alguien
    decida, de forma explícita, si puede modificar algo.
    """
    async with Client(mcp) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}

    assert set(tools) == READ_ONLY_TOOLS | WRITE_TOOLS
    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True, name
        assert tools[name].annotations.destructive_hint is False, name
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False, name
        assert tools[name].annotations.destructive_hint is True, name


@pytest.mark.parametrize("tool", ["get_transaction", "cancel_payment"])
@pytest.mark.parametrize("bad_id", [
    "../../admin/api/users",
    "../wallet/balance",
    "not-a-uuid",
    "",
])
async def test_transaction_id_cannot_alter_the_path(payg0_api, monkeypatch, tool, bad_id):
    """Un ID malicioso se rechaza antes de llegar a Payg0."""
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool(tool, {"transaction_id": bad_id})

    assert result.is_error
    assert calls == []


async def test_validate_payment_sends_amount_as_exact_string(payg0_api, monkeypatch):
    """El monto viaja como string para no perder precisión con floats."""
    calls, responses = payg0_api
    responses["/api/v1/payments/validate"] = httpx.Response(200, json={"valid": True})
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("validate_payment", {"recipient": "@carlos", "amount": "150.50"})

    assert not result.is_error
    assert calls[0].method == "POST"
    assert json.loads(calls[0].content) == {"recipient": "@carlos", "amount": "150.50"}


@pytest.mark.parametrize("amount", ["0", "-10", "10.555", "abc"])
async def test_invalid_amounts_never_reach_payg0(payg0_api, monkeypatch, amount):
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("validate_payment", {"recipient": "@carlos", "amount": amount})

    assert result.is_error
    assert calls == []


async def test_limit_errors_show_payg0_message(payg0_api):
    """Los errores de límites de Payg0 llegan como objeto; se muestra su mensaje."""
    _, responses = payg0_api
    responses["/api/v1/payments/send"] = httpx.Response(
        422, json={"detail": {"error_code": "LIMIT_SINGLE_TX", "message": "Excede tu límite por operación."}},
    )

    with pytest.raises(ToolError, match="Excede tu límite por operación"):
        await client.request("POST", "/payments/send", VALID_KEY, json={})


async def test_get_history_rejects_out_of_range_limit(payg0_api, monkeypatch):
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("get_history", {"limit": 500})

    assert result.is_error
    assert calls == []
