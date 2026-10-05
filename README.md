# Payg0 MCP

Servidor [MCP](https://modelcontextprotocol.io) que conecta tu billetera de
[Payg0](https://api.payg0.io) con agentes de IA. Tu agente puede consultar tu
saldo e historial, y preparar pagos que **tú confirmas con tu NIP en payg0.io**.

## Cómo se envía un pago

1. Le pides a tu agente: *"Mándale 250 pesos a @carlos por la cena"*.
2. El agente llama `send_payment`. **No se mueve dinero:** Payg0 crea una
   solicitud y le devuelve un enlace.
3. Abres el enlace. Payg0 (no el agente) te muestra el monto y el destinatario,
   y confirmas escribiendo tu NIP.
4. El agente consulta `check_payment_status` y te confirma que se envió.

El enlace expira en 10 minutos y cada solicitud se ejecuta como máximo una vez.

## Seguridad

- **Tu NIP nunca pasa por el agente.** Solo se escribe en payg0.io, siguiendo
  la [especificación de MCP](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)
  para credenciales que autorizan transacciones. Ninguna herramienta acepta un
  NIP como parámetro. Si un agente te pide tu NIP en el chat, no se lo des.
- **El agente no puede aprobar pagos por su cuenta**, aunque sea manipulado:
  sin tu NIP en payg0.io, no se mueve dinero.
- **El servidor no guarda nada.** No tiene base de datos. Cada request trae tu
  API key, que se reenvía al API de Payg0 y se descarta. Payg0 es la única
  autoridad que la valida.
- **Tu API key nunca se registra** en los logs del servidor, ni viaja en la URL.
- **Usa una API key dedicada para tu agente**, creada en payg0.io → Perfil →
  API & Dev. Si dejas de usarla, revócala.
- Cada key tiene sus propios límites de uso (rate limiting).

## Herramientas

| Herramienta | Qué hace | Modifica algo |
|---|---|---|
| `get_balance` | Saldo total, en escrow y disponible para enviar (MXN) | No |
| `get_history` | Pagos enviados y recibidos, con filtro por estado | No |
| `get_transaction` | Detalle de una transacción por su ID | No |
| `lookup_user` | Verifica si un destinatario existe (por nickname o email) | No |
| `validate_payment` | Comprueba saldo y límites de un pago, sin ejecutarlo | No |
| `send_payment` | Prepara un pago y devuelve el enlace para confirmarlo con tu NIP | Crea una solicitud; no mueve dinero |
| `check_payment_status` | Indica si confirmaste, rechazaste o dejaste expirar un pago | No |
| `cancel_payment` | Cancela un pago pendiente que enviaste; el dinero regresa a tu saldo | Sí |

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
