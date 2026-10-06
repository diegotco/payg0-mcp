"""
Thin HTTP client for the public Payg0 API.

This MCP server has no database and no business logic of its own: every tool
forwards the user's API key to the Payg0 API, which is the only authority
that validates it. The server never stores or logs the key.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

# At INFO level httpx logs the full URL of every request, including query
# params (e.g. the email searched in lookup_user). User data must stay out of
# the server logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = os.environ.get("PAYG0_API_URL", "https://api.payg0.io").rstrip("/") + "/api/v1"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
KEY_PREFIX = "pyg0_"


def resolve_api_key(headers: Mapping[str, str] | None) -> str:
    """
    Returns the user's API key.

    - HTTP transport: from the `X-API-Key` or `Authorization: Bearer <key>` header.
    - stdio transport: from the `PAYG0_API_KEY` environment variable.

    Only the format is checked. Whether the key is valid is decided by the Payg0 API.
    """
    key = ""
    if headers is not None:
        # HTTP header names are case-insensitive; normalize them.
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
            "Missing Payg0 API key. Set it in your MCP client with the 'X-API-Key' header. "
            "You can create one at payg0.io → \"My profile\" (\"Mi perfil\" in Spanish) → \"API & Dev\"."
        )
    if not key.startswith(KEY_PREFIX):
        raise ToolError(f"The API key has an unexpected format (it must start with '{KEY_PREFIX}').")
    return key


def _error_message(response: httpx.Response) -> str:
    """Turns API errors into clear messages for the agent."""
    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None

    status = response.status_code
    if status == 401:
        return "The API key is invalid or has been revoked. Create a new one at payg0.io."
    if status == 404:
        return detail or "The requested resource was not found."
    if status == 429:
        return "Too many requests. Wait a minute before trying again."
    if status >= 500:
        return "Payg0 is unavailable right now. Try again later."
    if isinstance(detail, str):
        return detail
    # Limit errors arrive as an object: {"error_code": ..., "message": ...}
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return f"Payg0 error (HTTP {status})."


async def request(
    method: str,
    path: str,
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    """Calls the Payg0 API and returns the JSON body, or raises ToolError."""
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
    # `from None` avoids chaining the httpx exception, which carries the
    # request (including the X-API-Key header) and could end up in logs.
    except httpx.TimeoutException:
        raise ToolError("Payg0 took too long to respond. Try again.") from None
    except httpx.HTTPError:
        raise ToolError("Could not connect to Payg0. Try again later.") from None

    if response.is_error:
        raise ToolError(_error_message(response))
    return response.json()
