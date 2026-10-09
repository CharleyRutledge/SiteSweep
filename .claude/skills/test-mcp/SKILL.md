---
name: test-mcp
description: Test an MCP server with SiteSweep (handshake, tool lists, speed, security, tool poisoning, logins, connection types and versions), safe checks only, and explain the report in plain language.
---

# Test an MCP server with SiteSweep

Speak plainly: the person may not be a developer. Safe checks only: no tool is called unless they list it, and
then only if the server marks it read-only.

## 1. Ask what to test

Use AskUserQuestion:

- **Which server.** "A remote server (its address, e.g. https://example.ie/mcp)", "A local server started as a
  command (e.g. npx -y @example/server)" (only on their own computer: a cloud session can't run their local
  programs), or a settings file in `config/private/` on their own computer (never list or name these anywhere
  else).
- **Login.** If the server needs one, ask only for the *name* of the environment variable that holds the token
  (in `.env` on their computer). Never ask for the token itself, and never print `.env`.
- **Calling tools.** "Inspect only" (the default) or "Also call read-only tools": then ask which tools and with
  what harmless inputs, and put them under `call_readonly` in a settings file in `config/private/`.

## 2. In a cloud session: check the network

For a remote server, run `python -m ui_automation.reach <ADDRESS>` first and follow what it says, as /test does.

## 3. Run it

- One server: `python -m ui_automation.mcp_audit <ADDRESS> [--token-env NAME] [--sse]`
- A local command: `python -m ui_automation.mcp_audit --command "<COMMAND>"`
- A settings file (roles, read-only calls, several servers): `python -m ui_automation.mcp_audit --config <FILE>`
  (see `config/mcp.example.yaml`)

## 4. Explain the result

Read `reports/latest/summary.json`. Reply with one line (passed or failed, the server, how many checks), then what
failed grouped by cause, worst first, in plain words: what's wrong, why it matters, and how to fix it. Tool
poisoning findings (instructions hidden in tool descriptions) come first: say plainly not to connect an AI to
that server until it's fixed. Then say what passed and what was not run (and why). Never paste tokens.

For uptime monitoring of the server, offer `/reliability` (it checks MCP servers with `--mcp`).
