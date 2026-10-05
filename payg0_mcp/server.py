"""
Servidor MCP de Payg0.

Expone el saldo, historial y transacciones del usuario a agentes de IA.
Ninguna herramienta puede enviar dinero fuera de la billetera del usuario.
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
Payg0 es una plataforma de pagos P2P en pesos mexicanos (MXN). En esta fase el
dinero es simulado.

Puedes consultar el saldo, el historial y el detalle de transacciones, verificar
si un destinatario existe y validar si un pago sería aprobado. También puedes
cancelar un pago PENDING del usuario (los fondos regresan a su saldo); confirma
con el usuario antes de hacerlo. Ninguna herramienta puede enviar dinero.

Al reportar saldos, usa `available_balance` como el dinero que el usuario puede
enviar; `held_balance` está reservado por pagos pendientes.
"""

# Todas las herramientas de esta fase: solo leen y consultan un sistema externo.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

mcp = MCPServer(
    name="payg0",
    title="Payg0",
    description="Consulta tu billetera de Payg0: saldo, historial y transacciones.",
    instructions=INSTRUCTIONS,
    website_url="https://api.payg0.io",
    version="0.1.0",
)


@mcp.tool(title="Consultar saldo", annotations=READ_ONLY)
async def get_balance(ctx: Context) -> dict[str, Any]:
    """Devuelve el saldo de la billetera: total, en escrow y disponible para enviar (MXN)."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", "/wallet/balance", key)


@mcp.tool(title="Historial de pagos", annotations=READ_ONLY)
async def get_history(
    ctx: Context,
    status: Annotated[
        Literal["PENDING", "COMPLETED", "CANCELLED", "EXPIRED", "FAILED"] | None,
        Field(description="Filtra por estado. Omítelo para ver todos."),
    ] = None,
    page: Annotated[int, Field(ge=1, description="Página de resultados.")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="Resultados por página (máx. 100).")] = 20,
) -> dict[str, Any]:
    """Lista los pagos enviados y recibidos, del más reciente al más antiguo."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request(
        "GET", "/payments/history", key,
        params={"status": status, "page": page, "limit": limit},
    )


def _parse_transaction_id(transaction_id: str) -> uuid.UUID:
    """
    El ID va dentro de la URL: lo validamos como UUID para que nunca pueda
    alterar la ruta (p. ej. '../') y llegar a otros endpoints de Payg0.
    """
    try:
        return uuid.UUID(transaction_id)
    except ValueError:
        raise ToolError("El ID de transacción no es un UUID válido.") from None


@mcp.tool(title="Detalle de transacción", annotations=READ_ONLY)
async def get_transaction(
    ctx: Context,
    transaction_id: Annotated[str, Field(description="ID (UUID) de la transacción.")],
) -> dict[str, Any]:
    """Devuelve el detalle de una transacción: monto, estado, contraparte y fechas."""
    tx_id = _parse_transaction_id(transaction_id)
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", f"/payments/{tx_id}", key)


@mcp.tool(title="Buscar destinatario", annotations=READ_ONLY)
async def lookup_user(
    ctx: Context,
    query: Annotated[
        str,
        Field(min_length=1, max_length=255, description="Nickname (@carlos) o email del destinatario."),
    ],
) -> dict[str, Any]:
    """Verifica si un destinatario existe en Payg0 antes de enviarle dinero."""
    key = client.resolve_api_key(ctx.headers)
    return await client.request("GET", "/users/lookup", key, params={"q": query})


Amount = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=2, description="Monto en MXN, máximo 2 decimales."),
]
Recipient = Annotated[
    str,
    Field(min_length=1, max_length=255, description="Nickname (@carlos) o email del destinatario."),
]


@mcp.tool(title="Validar pago", annotations=READ_ONLY)
async def validate_payment(
    ctx: Context,
    recipient: Recipient,
    amount: Amount,
) -> dict[str, Any]:
    """
    Comprueba si un pago sería aprobado SIN ejecutarlo: saldo disponible y
    límites del usuario. No mueve dinero. Úsalo antes de proponer un envío.
    """
    key = client.resolve_api_key(ctx.headers)
    return await client.request(
        "POST", "/payments/validate", key,
        json={"recipient": recipient, "amount": str(amount)},
    )


@mcp.tool(
    title="Cancelar pago pendiente",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def cancel_payment(
    ctx: Context,
    transaction_id: Annotated[str, Field(description="ID (UUID) del pago PENDING a cancelar.")],
) -> dict[str, Any]:
    """
    Cancela un pago PENDING que el usuario envió (a alguien que aún no se ha
    registrado). Los fondos regresan al saldo disponible del usuario.
    Confirma con el usuario antes de cancelar.
    """
    tx_id = _parse_transaction_id(transaction_id)
    key = client.resolve_api_key(ctx.headers)
    return await client.request("POST", f"/payments/{tx_id}/cancel", key)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _transport_security() -> TransportSecuritySettings | None:
    """
    En producción, MCP_ALLOWED_HOSTS limita los headers Host aceptados
    (p. ej. 'mcp.payg0.io'). Si no está definida, la protección queda apagada
    para no romper el desarrollo local.
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
        # Sin estado: cada request trae su propia API key y no se guarda nada.
        stateless_http=True,
        transport_security=_transport_security(),
    )


if __name__ == "__main__":
    main()
