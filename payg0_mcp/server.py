"""
Servidor MCP de Payg0 — Fase 1 (solo lectura).

Expone el saldo, historial y transacciones del usuario a agentes de IA.
Ninguna herramienta de esta fase puede mover dinero.
"""
from __future__ import annotations

import os
import uuid
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

Estas herramientas son de SOLO LECTURA: puedes consultar el saldo, el historial y
el detalle de transacciones, y verificar si un destinatario existe. Ninguna puede
enviar ni cancelar pagos.

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


@mcp.tool(title="Detalle de transacción", annotations=READ_ONLY)
async def get_transaction(
    ctx: Context,
    transaction_id: Annotated[str, Field(description="ID (UUID) de la transacción.")],
) -> dict[str, Any]:
    """Devuelve el detalle de una transacción: monto, estado, contraparte y fechas."""
    # El ID va dentro de la URL: lo validamos como UUID para que nunca pueda
    # alterar la ruta (p. ej. '../') y llegar a otros endpoints de Payg0.
    try:
        tx_id = uuid.UUID(transaction_id)
    except ValueError:
        raise ToolError("El ID de transacción no es un UUID válido.") from None
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
