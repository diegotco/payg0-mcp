"""
Payg0 MCP server.

Exposes the user's wallet balance, payment history and transactions to AI
agents. Payments only execute once the user confirms them with their PIN on
payg0.io; the PIN never passes through the agent or this server.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from payg0_mcp import client

INSTRUCTIONS = """\
Payg0 is a peer-to-peer payments platform in Mexican pesos (MXN). In the
current phase, money is simulated.

You can check the balance, the payment history and transaction details, verify
that a recipient exists and validate whether a payment would be approved. You
can also cancel one of the user's PENDING payments (the funds return to their
balance); confirm with the user before doing so.

To send money, use send_payment: it does not move money. It returns a link
where the user confirms the payment with their PIN on payg0.io. Show them the
link, then use check_payment_status to find out whether they confirmed it.
NEVER ask for the user's PIN in the chat: it is only entered on payg0.io.

When reporting balances, use `available_balance` as the money the user can
send; `held_balance` is reserved by pending payments.
"""

# Tools that only read from an external system.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

mcp = MCPServer(
    name="payg0",
    title="Payg0",
    description="Use your Payg0 wallet from AI agents: balance, history and payments confirmed with your PIN.",
    instructions=INSTRUCTIONS,
    website_url="https://api.payg0.io",
    version="0.1.0",
)


@mcp.tool(title="Get balance", annotations=READ_ONLY)
async def get_balance(ctx: Context) -> dict[str, Any]:
    """Returns the wallet balance: total, held in escrow, and available to send (MXN)."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", "/wallet/balance", key)


@mcp.tool(title="Payment history", annotations=READ_ONLY)
async def get_history(
    ctx: Context,
    status: Annotated[
        Literal["PENDING", "COMPLETED", "CANCELLED", "EXPIRED", "FAILED"] | None,
        Field(description="Filter by status. Omit it to list all."),
    ] = None,
    page: Annotated[int, Field(ge=1, description="Results page.")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="Results per page (max 100).")] = 20,
) -> dict[str, Any]:
    """Lists sent and received payments, most recent first."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request(
        "GET", "/payments/history", key,
        params={"status": status, "page": page, "limit": limit},
    )


def _parse_transaction_id(transaction_id: str) -> uuid.UUID:
    """
    The ID goes into the URL path: validate it as a UUID so it can never alter
    the path (e.g. '../') and reach other Payg0 endpoints.
    """
    try:
        return uuid.UUID(transaction_id)
    except ValueError:
        raise ToolError("The transaction ID is not a valid UUID.") from None


@mcp.tool(title="Transaction details", annotations=READ_ONLY)
async def get_transaction(
    ctx: Context,
    transaction_id: Annotated[str, Field(description="Transaction ID (UUID).")],
) -> dict[str, Any]:
    """Returns a transaction's details: amount, status, counterparty and dates."""
    tx_id = _parse_transaction_id(transaction_id)
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", f"/payments/{tx_id}", key)


@mcp.tool(title="Look up recipient", annotations=READ_ONLY)
async def lookup_user(
    ctx: Context,
    query: Annotated[
        str,
        Field(min_length=1, max_length=255, description="Recipient's nickname (@carlos) or email."),
    ],
) -> dict[str, Any]:
    """Checks whether a recipient exists on Payg0 before sending them money."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", "/users/lookup", key, params={"q": query})


Amount = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=2, description="Amount in MXN, at most 2 decimal places."),
]
Recipient = Annotated[
    str,
    Field(min_length=1, max_length=255, description="Recipient's nickname (@carlos) or email."),
]


@mcp.tool(title="Validate payment", annotations=READ_ONLY)
async def validate_payment(
    ctx: Context,
    recipient: Recipient,
    amount: Amount,
) -> dict[str, Any]:
    """
    Checks whether a payment would be approved WITHOUT executing it: available
    balance and the user's limits. Moves no money. Use it before proposing a
    payment.
    """
    key = client.resolve_api_key(ctx.headers)
    return await client.request(
        "POST", "/payments/validate", key,
        json={"recipient": recipient, "amount": str(amount)},
    )


@mcp.tool(
    title="Cancel pending payment",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def cancel_payment(
    ctx: Context,
    transaction_id: Annotated[str, Field(description="ID (UUID) of the PENDING payment to cancel.")],
) -> dict[str, Any]:
    """
    Cancels a PENDING payment the user sent (to someone who has not signed up
    yet). The funds return to the user's available balance. Confirm with the
    user before cancelling.
    """
    tx_id = _parse_transaction_id(transaction_id)
    key = client.resolve_api_key(ctx.headers)
    return await client.request("POST", f"/payments/{tx_id}/cancel", key)


@mcp.tool(
    title="Send payment (requires confirmation)",
    annotations=ToolAnnotations(
        read_only_hint=False,
        # This tool moves no money: it only creates a request that the user
        # confirms with their PIN on payg0.io.
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
async def send_payment(
    ctx: Context,
    recipient: Recipient,
    amount: Amount,
    description: Annotated[str | None, Field(max_length=500, description="Payment description (optional).")] = None,
) -> dict[str, Any]:
    """
    Prepares a payment that the user must confirm with their PIN on payg0.io.
    It does NOT move money: it returns a link (`confirm_url`) that you must show
    the user. The link expires in 10 minutes. Never ask for the PIN in the chat.
    Then use check_payment_status to find out whether they confirmed it.
    """
    key = client.resolve_api_key(ctx.headers)
    body: dict[str, Any] = {"recipient": recipient, "amount": str(amount)}
    if description:
        body["description"] = description
    intent = await client.request("POST", "/payments/intents", key, json=body)
    intent["next_step"] = (
        "Show confirm_url to the user and ask them to open it and confirm with their PIN. "
        "No money has moved."
    )
    return intent


@mcp.tool(title="Payment confirmation status", annotations=READ_ONLY)
async def check_payment_status(
    ctx: Context,
    payment_id: Annotated[str, Field(description="`id` returned by send_payment.")],
) -> dict[str, Any]:
    """
    Tells whether the user has confirmed a payment created with send_payment.
    Statuses: AWAITING_CONFIRMATION, CONFIRMED (includes transaction_id),
    DECLINED, EXPIRED or FAILED (includes failure_reason).
    """
    try:
        intent_id = uuid.UUID(payment_id)
    except ValueError:
        raise ToolError("The payment ID is not a valid UUID.") from None
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", f"/payments/intents/{intent_id}", key)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _transport_security() -> TransportSecuritySettings | None:
    """
    In production, MCP_ALLOWED_HOSTS restricts the accepted Host headers
    (e.g. 'mcp.payg0.io'). When unset, the protection is off so local
    development keeps working.
    """
    hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"https://{h}" for h in hosts],
    )


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        # Stateless: every request carries its own API key and nothing is stored.
        stateless_http=True,
        transport_security=_transport_security(),
    )


if __name__ == "__main__":
    main()
