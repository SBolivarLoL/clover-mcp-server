# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 0.x (pre-release) | Yes |

## Threat Model Summary

clover-mcp is a local stdio MCP server. Its threat surface:

- **Access tokens** — stored in env vars or a file at `CLOVER_TOKEN_STORE` (mode 0600). Never logged. Never transmitted to any party except Clover's API endpoints.
- **PII** — customer names, emails, phone numbers are fetched from Clover on demand and returned only to the calling LLM context. They are never cached to disk, logged, or transmitted elsewhere.
- **Card data** — the shaping layer (`shaping.py`) explicitly blocks `cardTransaction`, `cards`, `token`, `pan`, and `href` fields from ever appearing in tool outputs. See `tests/contract/test_shaping_allowlist.py`.
- **Write operations** — the server does not support refunds, voids, payment capture, or charge creation. Write tools require exact IDs and expected-current-value pre-checks to prevent stale-context overwrites.
- **No outbound network** beyond Clover's documented REST API endpoints.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report privately to: **mikeldev62@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (optional)

You will receive an acknowledgement within 72 hours. We aim to patch and release within 14 days for critical issues.
