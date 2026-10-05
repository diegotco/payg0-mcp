"""
Cliente HTTP delgado hacia el API público de Payg0.

Este servidor MCP no tiene base de datos ni lógica de negocio propia: cada
herramienta reenvía la API key del usuario al API de Payg0, que es la única
autoridad que la valida. El servidor nunca almacena ni registra la key.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

# httpx registra en INFO la URL completa de cada request, incluidos los query
# params (p. ej. el email buscado en lookup_user). No queremos datos de
# usuarios en los logs del servidor.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = os.environ.get("PAYG0_API_URL", "https://api.payg0.io").rstrip("/") + "/api/v1"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
KEY_PREFIX = "pyg0_"


def resolve_api_key(headers: Mapping[str, str] | None) -> str:
    """
    Obtiene la API key del usuario.

    - Transporte HTTP: del header `X-API-Key` o `Authorization: Bearer <key>`.
    - Transporte stdio: de la variable de entorno `PAYG0_API_KEY`.

    Solo comprueba el formato. La validez real la decide el API de Payg0.
    """
    key = ""
    if headers is not None:
        # Los headers HTTP no distinguen mayúsculas; normalizamos.
        lowered = {k.lower(): v for k, v in headers.items()}
        key = lowered.get("x-api-key", "")
        if not key:
            auth = lowered.get("authorization", "")
            if auth.lower().startswith("bearer "):
                key = auth[7:]
    else:
        key = os.environ.get("PAYG0_API_KEY", "")

    key = key.strip()
    if not key:
        raise ToolError(
            "Falta la API key de Payg0. Configúrala en tu cliente MCP con el header "
            "'X-API-Key'. Puedes crear una en payg0.io → Perfil → API & Dev."
        )
    if not key.startswith(KEY_PREFIX):
        raise ToolError(
            f"La API key no tiene el formato esperado (debe empezar con '{KEY_PREFIX}')."
        )
    return key


def _error_message(response: httpx.Response) -> str:
    """Traduce errores del API a mensajes claros para el agente."""
    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None

    status = response.status_code
    if status == 401:
        return "La API key es inválida o fue revocada. Genera una nueva en payg0.io."
    if status == 404:
        return detail or "No se encontró el recurso solicitado."
    if status == 429:
        return "Demasiadas solicitudes. Espera un minuto antes de intentar de nuevo."
    if status >= 500:
        return "Payg0 no está disponible en este momento. Intenta más tarde."
    if isinstance(detail, str):
        return detail
    # Los errores de límites llegan como objeto: {"error_code": ..., "message": ...}
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return f"Error de Payg0 (HTTP {status})."


async def request(
    method: str,
    path: str,
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    """Llama al API de Payg0 y devuelve el JSON, o levanta ToolError."""
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(
                method,
                f"{API_URL}{path}",
                headers={"X-API-Key": api_key, "User-Agent": "payg0-mcp"},
                params=clean_params,
                json=json,
            )
    # `from None` evita encadenar la excepción de httpx, que lleva adjunto el
    # request con el header X-API-Key y podría terminar en logs.
    except httpx.TimeoutException:
        raise ToolError("Payg0 tardó demasiado en responder. Intenta de nuevo.") from None
    except httpx.HTTPError:
        raise ToolError("No se pudo conectar con Payg0. Intenta más tarde.") from None

    if response.is_error:
        raise ToolError(_error_message(response))
    return response.json()
