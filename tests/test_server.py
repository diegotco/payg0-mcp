"""
Tests for the Payg0 MCP server.

They never touch the network: the Payg0 API is simulated with httpx.MockTransport.
"""
import json

import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from payg0_mcp import client
from payg0_mcp.server import mcp

VALID_KEY = "pyg0_test_abc123"


# ─── API key resolution ──────────────────────────────────────────────────────

def test_key_from_x_api_key_header():
    assert client.resolve_api_key({"X-API-Key": VALID_KEY}) == VALID_KEY


def test_key_from_bearer_header():
    assert client.resolve_api_key({"Authorization": f"Bearer {VALID_KEY}"}) == VALID_KEY


def test_header_lookup_is_case_insensitive():
    assert client.resolve_api_key({"x-api-key": VALID_KEY}) == VALID_KEY


def test_key_from_env_on_stdio(monkeypatch):
    """stdio has no headers: the key comes from PAYG0_API_KEY."""
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)
    assert client.resolve_api_key(None) == VALID_KEY


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.delenv("PAYG0_API_KEY", raising=False)
    with pytest.raises(ToolError, match="Missing Payg0 API key"):
        client.resolve_api_key({})


def test_wrong_prefix_is_rejected():
    with pytest.raises(ToolError, match="unexpected format"):
        client.resolve_api_key({"X-API-Key": "sk_live_abc"})


# ─── Calls to the (simulated) Payg0 API ──────────────────────────────────────

@pytest.fixture
def payg0_api(monkeypatch):
    """Replaces the network with a simulated Payg0 API and records every request."""
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
    # The key must never travel in the URL.
    assert VALID_KEY not in str(calls[0].url)


@pytest.mark.parametrize("status,expected", [
    (401, "invalid or has been revoked"),
    (429, "Too many requests"),
    (500, "unavailable"),
    (503, "unavailable"),
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


# ─── MCP tools ───────────────────────────────────────────────────────────────

# Expected (read_only_hint, destructive_hint) for every tool.
EXPECTED_ANNOTATIONS = {
    "get_balance": (True, False),
    "get_history": (True, False),
    "get_transaction": (True, False),
    "lookup_user": (True, False),
    "validate_payment": (True, False),
    "check_payment_status": (True, False),
    "cancel_payment": (False, True),
    # Writes (creates a request) but moves no money: the user confirms with their PIN.
    "send_payment": (False, False),
}


async def test_every_tool_is_classified():
    """
    Regression guard: every tool must be classified here on purpose. A new
    tool fails this test until someone explicitly decides whether it can
    modify anything.
    """
    async with Client(mcp) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}

    assert set(tools) == set(EXPECTED_ANNOTATIONS)
    for name, (read_only, destructive) in EXPECTED_ANNOTATIONS.items():
        assert tools[name].annotations.read_only_hint is read_only, name
        assert tools[name].annotations.destructive_hint is destructive, name


async def test_no_tool_accepts_a_pin():
    """
    The PIN is only entered on payg0.io. No tool may receive it: if it went
    through the agent it would stay in the chat history and could be reused
    to authorize other payments.
    """
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools

    # "nip" is the Spanish word for PIN, which Payg0 users may also use.
    forbidden = {"pin", "nip", "passcode", "password"}
    for tool in tools:
        params = {p.lower() for p in tool.input_schema.get("properties", {})}
        assert not params & forbidden, tool.name


@pytest.mark.parametrize("tool,param", [
    ("get_transaction", "transaction_id"),
    ("cancel_payment", "transaction_id"),
    ("check_payment_status", "payment_id"),
])
@pytest.mark.parametrize("bad_id", [
    "../../admin/api/users",
    "../wallet/balance",
    "not-a-uuid",
    "",
])
async def test_ids_cannot_alter_the_path(payg0_api, monkeypatch, tool, param, bad_id):
    """A malicious ID is rejected before it reaches Payg0."""
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool(tool, {param: bad_id})

    assert result.is_error
    assert calls == []


async def test_send_payment_only_creates_a_confirmation_request(payg0_api, monkeypatch):
    """send_payment never calls /payments/send: it only creates a request to confirm."""
    calls, responses = payg0_api
    responses["/api/v1/payments/intents"] = httpx.Response(201, json={
        "id": "3f1c1b9e-0000-4000-8000-000000000000",
        "status": "AWAITING_CONFIRMATION",
        "confirm_url": "https://api.payg0.io/confirm-payment/3f1c1b9e-0000-4000-8000-000000000000",
    })
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool(
            "send_payment", {"recipient": "@carlos", "amount": "250.00", "description": "Dinner"},
        )

    assert not result.is_error
    assert [call.url.path for call in calls] == ["/api/v1/payments/intents"]
    assert json.loads(calls[0].content) == {"recipient": "@carlos", "amount": "250.00", "description": "Dinner"}
    data = result.structured_content
    assert data["confirm_url"].endswith("/confirm-payment/3f1c1b9e-0000-4000-8000-000000000000")
    assert "No money has moved" in data["next_step"]


async def test_validate_payment_sends_amount_as_exact_string(payg0_api, monkeypatch):
    """The amount travels as a string so floats cannot lose precision."""
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
    """Payg0 limit errors arrive as an object; their message is surfaced."""
    _, responses = payg0_api
    responses["/api/v1/payments/send"] = httpx.Response(
        422, json={"detail": {"error_code": "LIMIT_SINGLE_TX", "message": "Exceeds your per-transaction limit."}},
    )

    with pytest.raises(ToolError, match="Exceeds your per-transaction limit"):
        await client.request("POST", "/payments/send", VALID_KEY, json={})


async def test_get_history_rejects_out_of_range_limit(payg0_api, monkeypatch):
    calls, _ = payg0_api
    monkeypatch.setenv("PAYG0_API_KEY", VALID_KEY)

    async with Client(mcp) as c:
        result = await c.call_tool("get_history", {"limit": 500})

    assert result.is_error
    assert calls == []
