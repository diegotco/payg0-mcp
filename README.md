# Payg0 MCP

Servidor [MCP](https://modelcontextprotocol.io) que conecta tu billetera de
[Payg0](https://api.payg0.io) con agentes de IA. Tu agente puede consultar tu
saldo, tu historial de pagos y el detalle de tus transacciones.

> **Fase 1 — solo lectura.** Ninguna herramienta de esta versión puede enviar,
> cancelar ni mover dinero.

## Seguridad

- **El servidor no guarda nada.** No tiene base de datos. Cada request trae tu
  API key, que se reenvía al API de Payg0 y se descarta. Payg0 es la única
  autoridad que la valida.
- **Tu API key nunca se registra** en los logs del servidor, ni viaja en la URL.
- **Usa una API key dedicada para tu agente.** Créala en payg0.io → Perfil →
  API & Dev, y déjala **sin** el permiso de pagos. Así, aunque el agente fuera
  manipulado, no podría mover dinero. Si dejas de usarla, revócala.
- Cada key tiene sus propios límites de uso (rate limiting).

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `get_balance` | Saldo total, en escrow y disponible para enviar (MXN) |
| `get_history` | Pagos enviados y recibidos, con filtro por estado |
| `get_transaction` | Detalle de una transacción por su ID |
| `lookup_user` | Verifica si un destinatario existe (por nickname o email) |

Todas están marcadas como `readOnlyHint: true` y `destructiveHint: false`.

## Conectar desde tu cliente MCP

Configura el servidor remoto con tu API key en el header `X-API-Key`:

```json
{
  "mcpServers": {
    "payg0": {
      "url": "https://mcp.payg0.io/mcp",
      "headers": {
        "X-API-Key": "pyg0_live_tu_key_aqui"
      }
    }
  }
}
```

También se acepta `Authorization: Bearer <key>`.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Tests (no llaman a la red)
pytest

# Servidor HTTP en http://localhost:8000/mcp
python -m payg0_mcp.server

# O en modo stdio, con la key en una variable de entorno
MCP_TRANSPORT=stdio PAYG0_API_KEY=pyg0_test_... python -m payg0_mcp.server
```

## Configuración

| Variable | Por defecto | Descripción |
|---|---|---|
| `MCP_TRANSPORT` | `streamable-http` | `streamable-http` o `stdio` |
| `PORT` | `8000` | Puerto HTTP |
| `PAYG0_API_KEY` | — | Solo en modo `stdio` |
| `PAYG0_API_URL` | `https://api.payg0.io` | URL del API de Payg0 |
| `MCP_ALLOWED_HOSTS` | — | Hosts permitidos en producción (p. ej. `mcp.payg0.io`) |
