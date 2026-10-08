# Payg0 MCP

[MCP](https://modelcontextprotocol.io) server that connects your
[Payg0](https://api.payg0.io) wallet to AI agents. Your agent can check your
balance and history, and prepare payments that **you confirm with your PIN on
payg0.io**.

## How a payment is sent

1. You ask your agent: *"Send 250 pesos to @carlos for dinner"*.
2. The agent calls `send_payment`. **No money moves:** Payg0 creates a request
   and returns a link to the agent.
3. You open the link. Payg0 (not the agent) shows you the amount and the
   recipient, and you confirm by entering your PIN.
4. The agent calls `check_payment_status` and tells you the payment went through.

The link expires in 10 minutes, and each request executes at most once.

## Security

- **Your PIN never passes through the agent.** It is only entered on payg0.io,
  following the [MCP specification](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)
  for credentials that authorize transactions. No tool accepts a PIN as a
  parameter. If an agent asks for your PIN in the chat, don't give it.
- **The agent cannot approve payments on its own**, even if it is manipulated:
  without your PIN on payg0.io, no money moves.
- **The server stores nothing.** It has no database. Every request carries your
  API key, which is forwarded to the Payg0 API and discarded. Payg0 is the only
  authority that validates it.
- **Your API key is never logged** by the server, and it never travels in the URL.
- **Use a dedicated API key for your agent**, created at payg0.io → "My profile"
  ("Mi perfil" in Spanish) → "API & Dev". Revoke it when you stop using it.
- Each key has its own rate limits.
- Found a vulnerability? Report it privately: see [SECURITY.md](SECURITY.md).

## Tools

| Tool | What it does | Modifies anything |
|---|---|---|
| `get_balance` | Total balance, amount held in escrow, and amount available to send (MXN) | No |
| `get_history` | Sent and received payments, filterable by status | No |
| `get_transaction` | Details of a transaction by ID | No |
| `lookup_user` | Checks whether a recipient exists (by nickname or email) | No |
| `validate_payment` | Checks balance and limits for a payment without executing it | No |
| `send_payment` | Prepares a payment and returns the link to confirm it with your PIN | Creates a request; moves no money |
| `check_payment_status` | Tells whether you confirmed, declined, or let a payment expire | No |
| `cancel_payment` | Cancels a pending payment you sent; the money returns to your balance | Yes |

## Connect from your MCP client

Configure the remote server with your API key in the `X-API-Key` header:

```json
{
  "mcpServers": {
    "payg0": {
      "url": "https://mcp.payg0.io/mcp",
      "headers": {
        "X-API-Key": "pyg0_live_your_key_here"
      }
    }
  }
}
```

`Authorization: Bearer <key>` is also accepted.

### Cursor

Install it from **[cursor.directory/plugins/payg0](https://cursor.directory/plugins/payg0)**
("Add to Cursor"). Then give Cursor your key: set `PAYG0_API_KEY` under
**Plugins → Configure**, or, if the server's config shows `${PAYG0_API_KEY}`
in the `X-API-Key` header, replace it with your key.

This repository is the [Cursor plugin](https://cursor.com/docs/plugins):
[`.cursor-plugin/plugin.json`](.cursor-plugin/plugin.json) and
[`mcp.json`](mcp.json). No key is stored in it.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Tests (no network access)
pytest

# HTTP server at http://localhost:8000/mcp
python -m payg0_mcp.server

# Or in stdio mode, with the key in an environment variable
MCP_TRANSPORT=stdio PAYG0_API_KEY=pyg0_test_... python -m payg0_mcp.server
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `streamable-http` | `streamable-http` or `stdio` |
| `PORT` | `8000` | HTTP port |
| `PAYG0_API_KEY` | — | Only in `stdio` mode |
| `PAYG0_API_URL` | `https://api.payg0.io` | Payg0 API URL |
| `MCP_ALLOWED_HOSTS` | — | Allowed hosts in production (e.g. `mcp.payg0.io`) |

## License

[MIT](LICENSE) © 2026 Diego Leon Ullauri. This license covers the code of this MCP server; using it requires a Payg0 account and API key, subject to the terms of [payg0.io](https://payg0.io).
