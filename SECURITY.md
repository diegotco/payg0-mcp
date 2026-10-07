# Security Policy

## Reporting a vulnerability

**Please don't report security issues in public issues, pull requests or
discussions.** Report them privately through either channel:

- **GitHub:** [report a vulnerability](https://github.com/diegotco/payg0-mcp/security/advisories/new)
  (Security tab → "Report a vulnerability").
- **Email:** support@payg0.io, with "Security" in the subject.

Please include:

- What the issue is and what an attacker could do with it.
- Steps to reproduce it (requests, tool calls or code).
- The version or commit you tested.

We will confirm we received your report, keep you updated while we work on a
fix, and credit you once it is fixed, unless you prefer to stay anonymous.

## Scope

- This MCP server: the code in this repository and the hosted server at
  `https://mcp.payg0.io/mcp`.
- The Payg0 API it talks to (`https://api.payg0.io`) and payg0.io: report those
  through the same channels.

Only the latest version on `main` (the one running at mcp.payg0.io) receives
security fixes.

## Testing guidelines

- Use your own account and a dedicated API key, and revoke the key when you
  are done.
- Don't access, modify or delete other people's data or money. If you come
  across someone else's data, stop and tell us.
- Don't run denial-of-service attacks, spam, or social engineering against
  Payg0 users or staff.
- Never share PINs, passwords or API keys in a report, yours or anyone else's.
