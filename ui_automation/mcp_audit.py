"""SiteSweep for MCP servers: the website checks, applied to a Model Context Protocol server.

    python -m ui_automation.mcp_audit https://example.ie/mcp
    python -m ui_automation.mcp_audit --command "npx -y @example/mcp-server"
    python -m ui_automation.mcp_audit --config config/mcp.yaml

Safe by default: it never calls a tool. It runs the handshake, lists tools, resources and prompts, and inspects
them. Tools are only called when the settings file names them with their inputs (`call_readonly`), and only if
the server marks them read-only. Logins come from environment variables (`token_env`), never from files.

Checks (each with the part of the MCP specification it comes from, version 2025-06-18):
handshake and lists, speed, security (HTTPS, Origin checking, CORS, refusing callers with no login, OAuth
metadata, versions and stack traces given away), tool safety (instructions hidden in tool descriptions, write
tools not marked), each login seeing only its tools, connection types and protocol versions, and read-only tools
that answer. The results are a SiteSweep report (summary.html / summary.json).
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]  # newest first; the ones this checker knows
CLIENT = {"name": "SiteSweep", "version": "1"}
TEST_ORIGIN = "https://sitesweep-origin-check.invalid"
SPEC = "MCP specification 2025-06-18"

# Words in tool descriptions that speak to the AI rather than describe the tool ("tool poisoning").
HIDDEN_INSTRUCTIONS = [
    (r"ignore (all |any )?(previous|prior|other) (instructions|tools)", "tells the AI to ignore its instructions"),
    (r"do not (tell|inform|mention|show)[^.]{0,40}\b(user|human)", "tells the AI to keep something from the user"),
    (r"<\s*(important|system|instructions?)\s*>", "hidden instruction block"),
    (r"before (using|calling) (any|every|all)?\s*(other )?tools?", "tries to run before every other tool"),
    (r"(~/\.ssh|id_rsa|\.env\b|\.aws/credentials|private key|api[_ ]?key|password)", "asks for secrets or keys"),
    (r"(send|forward|post|upload)[^.]{0,60}(to|at) https?://", "sends data to another address"),
    ("[\\u200b-\\u200f\\u2060\\ufeff]", "invisible characters"),  # written as escapes: never the characters themselves
]
WRITE_WORDS = re.compile(r"(^|_|-)(delete|remove|drop|destroy|write|update|create|insert|send|post|pay|transfer|"
                         r"execute|exec|run|kill|purge|reset|move|rename)($|_|-)", re.I)
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
STACK = re.compile(r"Traceback \(most recent call last\)|\bat [\w.$<>]+ \(.*:\d+:\d+\)|File \".*\", line \d+")


class McpError(Exception):
    pass


@dataclass
class Reply:
    body: dict | None  # the JSON-RPC response ({"result": ...} or {"error": ...}), None when there was none
    status: int = 0
    headers: dict = field(default_factory=dict)
    ms: int = 0
    raw: str = ""


def _verify() -> Any:
    return os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") or True


def _sse_messages(lines: Any) -> Any:
    """JSON-RPC messages from a text/event-stream, one per event."""
    event, data = "message", []
    for line in lines:
        line = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


class HttpTransport:
    """Streamable HTTP: every message is a POST; the answer is JSON or an event stream."""
    kind = "streamable HTTP"

    def __init__(self, url: str, token: str = "", origin: str = "", timeout: float = 30) -> None:
        self.url, self.token, self.origin, self.timeout = url, token, origin, timeout
        self.session_id = ""
        self.version = ""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "User-Agent": "SiteSweep MCP check"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.origin:
            h["Origin"] = self.origin
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.version:
            h["MCP-Protocol-Version"] = self.version
        return h

    def send(self, message: dict) -> Reply:
        started = time.monotonic()
        try:
            r = requests.post(self.url, json=message, headers=self._headers(), timeout=self.timeout, stream=True,
                              verify=_verify())
        except requests.RequestException as exc:
            raise McpError(f"no answer: {type(exc).__name__}: {str(exc)[:200]}") from exc
        reply = Reply(None, r.status_code, {k.lower(): v for k, v in r.headers.items()})
        if r.headers.get("Mcp-Session-Id"):
            self.session_id = r.headers["Mcp-Session-Id"]
        kind = r.headers.get("Content-Type", "")
        if "id" in message and r.status_code < 400 and "text/event-stream" in kind:
            for _, data in _sse_messages(r.iter_lines(chunk_size=1)):
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == message["id"]:
                    reply.body = msg
                    break
        else:
            reply.raw = r.text[:20_000]
            try:
                reply.body = json.loads(reply.raw) if reply.raw.strip() else None
            except ValueError:
                reply.body = None
        r.close()
        reply.ms = int((time.monotonic() - started) * 1000)
        return reply

    def close(self) -> None:
        if self.session_id:
            try:
                requests.delete(self.url, headers=self._headers(), timeout=5, verify=_verify())
            except requests.RequestException:
                pass


class SseTransport:
    """The older HTTP+SSE transport (2024-11-05): a GET event stream that names where to POST."""
    kind = "HTTP+SSE (older)"

    def __init__(self, url: str, token: str = "", timeout: float = 30) -> None:
        self.url, self.token, self.timeout = url, token, timeout
        self.messages: queue.Queue = queue.Queue()
        headers = {"Accept": "text/event-stream", "User-Agent": "SiteSweep MCP check"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            self.stream = requests.get(url, headers=headers, stream=True, timeout=timeout, verify=_verify())
        except requests.RequestException as exc:
            raise McpError(f"no answer: {type(exc).__name__}") from exc
        if self.stream.status_code >= 400 or "text/event-stream" not in self.stream.headers.get("Content-Type", ""):
            self.stream.close()
            raise McpError(f"no event stream (HTTP {self.stream.status_code})")
        self.endpoint = ""
        ready = threading.Event()

        def read() -> None:
            try:
                for event, data in _sse_messages(self.stream.iter_lines(chunk_size=1)):
                    if event == "endpoint":
                        self.endpoint = urljoin(url, data.strip())
                        ready.set()
                    else:
                        try:
                            self.messages.put(json.loads(data))
                        except ValueError:
                            pass
            except Exception:  # noqa: BLE001 - the stream closed
                pass
            ready.set()

        threading.Thread(target=read, daemon=True).start()
        # A newer server may answer this GET with its own notification stream: give up on "endpoint" after 10 s.
        if not ready.wait(min(timeout, 10)) or not self.endpoint:
            self.close()
            raise McpError("the event stream never said where to send messages")

    def send(self, message: dict) -> Reply:
        started = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = requests.post(self.endpoint, json=message, headers=headers, timeout=self.timeout, verify=_verify())
        reply = Reply(None, r.status_code, {k.lower(): v for k, v in r.headers.items()}, raw=r.text[:2000])
        if "id" in message:
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    msg = self.messages.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if isinstance(msg, dict) and msg.get("id") == message["id"]:
                    reply.body = msg
                    break
        reply.ms = int((time.monotonic() - started) * 1000)
        return reply

    def close(self) -> None:
        try:
            self.stream.close()
        except Exception:  # noqa: BLE001
            pass


class StdioTransport:
    """A local server started as a command, one JSON message per line on stdin / stdout."""
    kind = "stdio (local command)"

    def __init__(self, command: str, env: dict | None = None, timeout: float = 30) -> None:
        self.timeout = timeout
        self.proc = subprocess.Popen(shlex.split(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # nosec B603
                                     stderr=subprocess.PIPE, text=True, env={**os.environ, **(env or {})})
        self.messages: queue.Queue = queue.Queue()

        def read() -> None:
            for line in self.proc.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({"_not_json": line[:200]})

        threading.Thread(target=read, daemon=True).start()

    def send(self, message: dict) -> Reply:
        started = time.monotonic()
        if self.proc.poll() is not None:
            raise McpError(f"the server stopped (exit code {self.proc.returncode})")
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        reply = Reply(None)
        if "id" in message:
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    msg = self.messages.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if "_not_json" in msg:
                    reply.raw += msg["_not_json"]
                elif msg.get("id") == message["id"]:
                    reply.body = msg
                    break
        reply.ms = int((time.monotonic() - started) * 1000)
        return reply

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Client:
    def __init__(self, transport: Any) -> None:
        self.t = transport
        self.next_id = 0

    def call(self, method: str, params: dict | None = None) -> Reply:
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        return self.t.send(msg)

    def notify(self, method: str) -> Reply:
        return self.t.send({"jsonrpc": "2.0", "method": method})

    def initialize(self, version: str = PROTOCOL_VERSIONS[0]) -> Reply:
        reply = self.call("initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": CLIENT})
        result = (reply.body or {}).get("result") or {}
        if isinstance(self.t, HttpTransport) and result.get("protocolVersion"):
            self.t.version = result["protocolVersion"]
        if result:
            self.notify("notifications/initialized")
        return reply

    def list_all(self, method: str, key: str) -> tuple[list, list[str], int]:
        """Every item of a paged list, problems, and the first page's time in ms."""
        items, problems, cursor, first_ms = [], [], None, 0
        for page in range(20):
            reply = self.call(method, {"cursor": cursor} if cursor else {})
            first_ms = first_ms or reply.ms
            body = reply.body or {}
            if "error" in body:
                problems.append(f"{method} answered with an error: {body['error'].get('message', '')[:120]}")
                break
            result = body.get("result")
            if not isinstance(result, dict) or not isinstance(result.get(key), list):
                problems.append(f"{method} didn't answer with a list of {key}")
                break
            items += result[key]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return items, problems, first_ms


@dataclass
class Check:
    name: str  # test name, e.g. "answers_the_handshake"
    about: str
    problems: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    not_run: str = ""  # why it didn't apply

    def table(self, title: str, columns: list[str], rows: list[list], note: str = "") -> None:
        self.tables.append({"title": title, "columns": columns, "rows": [[str(c) for c in r] for r in rows],
                            "note": note})


ABOUT = {
    "answers_the_handshake": "The MCP handshake (initialize): the server says which protocol version it speaks, "
                             "its name and what it offers, accepts that the client is ready, answers ping, and "
                             "answers an unknown request with the standard error. (" + SPEC + ": Lifecycle)",
    "lists_its_tools_correctly": "Every tool, resource and prompt the server offers is listed, page by page, and "
                                 "each tool has a usable name, a description and an input schema, so an AI knows "
                                 "when and how to use it. (" + SPEC + ": Tools, Resources, Prompts)",
    "answers_quickly": "How long the handshake and the tool list take, against the limit (budget_ms).",
    "is_served_securely": "Safe security checks, no attack-like requests: HTTPS, checking the Origin of requests "
                          "(the spec requires it, against DNS rebinding), CORS, refusing callers without a login, "
                          "the OAuth details a client needs, and no software versions or stack traces given away. "
                          "(" + SPEC + ": Transports, Authorization, Security best practices)",
    "tool_descriptions_are_safe": "Tool descriptions are read by the AI, so text in them that gives the AI orders "
                                  "(ignore instructions, hide things from the user, read keys, send data away) is "
                                  "an attack known as tool poisoning. Tools that change things should say so "
                                  "(destructiveHint) so clients can ask the person first. (OWASP Top 10 for LLM "
                                  "Applications 2025: LLM01 Prompt Injection; " + SPEC + ": Tool annotations)",
    "each_login_sees_only_its_tools": "Each login (a token from an environment variable) sees the tools it "
                                      "should, and none it shouldn't.",
    "works_with_each_connection_and_version": "Which connection types (streamable HTTP, the older HTTP+SSE, or a "
                                              "local command) and protocol versions the server works with, so "
                                              "older and newer clients can use it.",
    "read_only_tools_work": "Calls only the tools you listed, with your inputs, and only if the server marks them "
                            "read-only: each must answer without an error.",
}


def _open(server: dict, token: str = "", origin: str = "") -> Any:
    if server.get("command"):
        return StdioTransport(server["command"], server.get("env"))
    if server.get("transport") == "sse":
        return SseTransport(server["url"], token)
    return HttpTransport(server["url"], token, origin)


def _token(server: dict, env_name: str = "") -> str:
    name = env_name or server.get("token_env", "")
    return os.environ.get(name, "") if name else ""


def audit(server: dict, budget_ms: int = 2000) -> list[Check]:
    """All checks on one server: {"name", "url" | "command", "transport", "token_env", "roles", "call_readonly"}."""
    checks = {k: Check(k, ABOUT[k]) for k in ABOUT}
    hand, lists, speed, sec, safety, roles, compat, calls = (checks[k] for k in ABOUT)
    token = _token(server)
    try:
        t = _open(server, token)
    except (McpError, OSError) as exc:
        hand.problems.append(f"Could not connect: {exc}")
        for c in checks.values():
            if c is not hand:
                c.not_run = "the server could not be reached"
        return list(checks.values())
    client = Client(t)
    try:
        try:
            init = client.initialize()
        except McpError as exc:
            hand.problems.append(f"Could not connect: {exc}")
            for c in checks.values():
                if c is not hand:
                    c.not_run = "the server could not be reached"
            return list(checks.values())
        result = (init.body or {}).get("result") or {}
        if not result:
            needs_login = init.status == 401 and not token
            err = (init.body or {}).get("error", {}).get("message") or f"HTTP {init.status} {init.raw[:120]}"
            if needs_login:  # refusing a caller with no login is right: the rest needs a token to check
                hand.not_run = ("the server needs a login: put a token in an environment variable and name it "
                                "with token_env (or --token-env)")
            else:
                hand.problems.append(f"initialize didn't succeed: {err}")
            for c in checks.values():
                if c not in (hand, sec):
                    c.not_run = hand.not_run or "the handshake failed"
            if isinstance(t, HttpTransport):
                _security(sec, server, init, token)
            else:
                sec.not_run = "a local command has no network connection to check"
            return list(checks.values())
        _handshake(hand, client, result, init)
        tools = _lists(lists, client, result)
        _speed(speed, init, client, budget_ms)
        if isinstance(t, HttpTransport):
            _security(sec, server, init, token)
        else:
            sec.not_run = "a local command has no network connection to check"
        _safety(safety, tools)
        _roles(roles, server, tools)
        _compat(compat, server, token)
        _calls(calls, client, server, tools)
    finally:
        t.close()
    return list(checks.values())


def _handshake(c: Check, client: Client, result: dict, init: Reply) -> None:
    version = result.get("protocolVersion", "")
    info = result.get("serverInfo") or {}
    caps = result.get("capabilities")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(version)):
        c.problems.append(f"protocolVersion is missing or not a date ({version!r})")
    if not info.get("name"):
        c.problems.append("serverInfo has no name")
    if not isinstance(caps, dict):
        c.problems.append("capabilities is missing")
    ping = client.call("ping")
    if not (ping.body and "result" in ping.body):
        c.problems.append("ping didn't answer with a result")
    unknown = client.call("sitesweep/no_such_method")
    code = ((unknown.body or {}).get("error") or {}).get("code")
    if code != -32601:
        c.problems.append(f"an unknown request should get error -32601 (method not found), got {code!r}")
    c.table("Handshake", ["Item", "Answer"], [
        ["Protocol version", version], ["Server", f"{info.get('name', '')} {info.get('version', '')}".strip()],
        ["Offers", ", ".join(k for k in (caps or {}) if k in ("tools", "resources", "prompts", "logging",
                                                               "completions")) or "nothing listed"],
        ["Instructions for the AI", "yes" if result.get("instructions") else "none"],
        ["ping", "answered" if ping.body and "result" in ping.body else "no answer"],
        ["Unknown request", f"error {code}" if code is not None else "no error"]])


def _lists(c: Check, client: Client, result: dict) -> list[dict]:
    caps = result.get("capabilities") or {}
    tools: list[dict] = []
    if "tools" in caps:
        tools, problems, _ = client.list_all("tools/list", "tools")
        c.problems += problems
    rows = []
    for tool in tools:
        name = str(tool.get("name", ""))
        issues = []
        if not TOOL_NAME.match(name):
            issues.append("name has spaces or unusual characters (some clients refuse it)")
        if len((tool.get("description") or "").strip()) < 10:
            issues.append("no real description, so an AI can't tell when to use it")
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            issues.append("inputSchema is missing or not an object schema")
        else:
            props = schema.get("properties") or {}
            bare = [p for p, s in props.items() if isinstance(s, dict) and not s.get("description")]
            if len(props) > 1 and len(bare) == len(props):  # one unexplained input is usually obvious; all is not
                issues.append(f"none of its inputs is described ({', '.join(bare[:5])})")
        c.problems += [f"{name or '(no name)'}: {i}" for i in issues]
        rows.append([name, (tool.get("description") or "")[:120], ", ".join((schema or {}).get("properties", {}))
                     if isinstance(schema, dict) else "", "; ".join(issues) or "fine"])
    names = [t.get("name") for t in tools]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        c.problems.append(f"tools listed twice: {', '.join(map(str, dupes))}")
    if "tools" in caps:
        c.table(f"{len(tools)} tool(s)", ["Tool", "Description", "Inputs", "Problems"], rows)
    for method, key, cap in (("resources/list", "resources", "resources"), ("prompts/list", "prompts", "prompts")):
        if cap in caps:
            items, problems, _ = client.list_all(method, key)
            c.problems += problems
            c.table(f"{len(items)} {key}", ["Name", "Description"],
                    [[i.get("name") or i.get("uri", ""), (i.get("description") or "")[:120]] for i in items[:50]])
    if not any(k in caps for k in ("tools", "resources", "prompts")):
        c.problems.append("the server offers no tools, resources or prompts")
    return tools


def _speed(c: Check, init: Reply, client: Client, budget_ms: int) -> None:
    rows = [["Handshake (initialize)", f"{init.ms} ms"]]
    listed = client.call("tools/list", {})
    rows.append(["Tool list", f"{listed.ms} ms"])
    for label, ms in (("handshake", init.ms), ("tool list", listed.ms)):
        if ms > budget_ms:
            c.problems.append(f"the {label} took {ms} ms (limit {budget_ms} ms)")
    c.table(f"Response times (limit {budget_ms} ms)", ["Request", "Time"], rows)


def _security(c: Check, server: dict, init: Reply, token: str) -> None:
    from ui_automation.local import is_local

    url = server["url"]
    rows = []
    local = is_local(url)
    if not url.startswith("https://") and not local:
        c.problems.append("not served over HTTPS: tokens and data can be read on the way")
    rows.append(["HTTPS", "yes" if url.startswith("https://") else "local address" if local else "no"])
    # Origin: a request claiming to come from another website must be refused (DNS rebinding).
    try:
        foreign = Client(HttpTransport(url, token, TEST_ORIGIN)).initialize()
        accepted = bool((foreign.body or {}).get("result"))
        # Where it matters: a server on this computer or network (DNS rebinding), or one that needs a login (another
        # website could use the visitor's). A public server with no login is meant to be callable from any page.
        guarded = local or bool(token)
        if accepted and guarded:
            c.problems.append(f"accepts requests from any website (Origin: {TEST_ORIGIN}); the spec requires "
                              "servers to check Origin, against DNS rebinding")
        rows.append(["Request from another website (Origin)", (f"refused (HTTP {foreign.status})" if not accepted
                     else "accepted" if guarded else "accepted (advice: fine for a public server with no login; "
                                                     "check Origin if it ever gets one)")])
        allow = foreign.headers.get("access-control-allow-origin", "")
        creds = foreign.headers.get("access-control-allow-credentials", "").lower() == "true"
        loose = allow in (TEST_ORIGIN, "*") and creds
        if loose and guarded:
            c.problems.append("CORS lets any website call it with the user's login")
        rows.append(["CORS", f"{allow or 'not set'}{' with credentials' if creds else ''}"
                     + (" (advice: drop credentials, as there is no login to protect)" if loose and not guarded else "")])
    except McpError as exc:
        rows.append(["Request from another website (Origin)", f"no answer ({exc})"])
    # Login: without the token, nothing may be listed.
    if token:
        anon = Client(HttpTransport(url))
        try:
            reply = anon.initialize()
            listed = anon.call("tools/list", {}) if (reply.body or {}).get("result") else reply
            open_ = bool((listed.body or {}).get("result"))
            if open_:
                c.problems.append("answers without a login: anyone can list and use its tools")
            rows.append(["Without a login", "refused" if not open_ else "answers"])
            if reply.status == 401:
                _oauth(c, rows, url, reply)
        except McpError as exc:
            rows.append(["Without a login", f"no answer ({exc})"])
    elif init.status == 401:
        rows.append(["Without a login", "refused (HTTP 401)"])
        _oauth(c, rows, url, init)
    else:
        rows.append(["Without a login", "no token set (token_env), so this server was checked as a public one"])
    leaks = [f"{k}: {init.headers[k]}" for k in ("server", "x-powered-by")
             if k in init.headers and re.search(r"\d+\.\d+", init.headers[k])]
    if leaks:
        c.problems.append("gives away software versions: " + "; ".join(leaks))
    rows.append(["Software versions in headers", "; ".join(leaks) or "none"])
    try:
        bad = HttpTransport(url, token).send({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
                                              "params": {"name": None}})
        text = json.dumps(bad.body) if bad.body else bad.raw
        if STACK.search(text or ""):
            c.problems.append("a malformed request gets a stack trace back (shows the server's code)")
        rows.append(["Malformed request", "stack trace shown" if STACK.search(text or "") else
                     f"refused (HTTP {bad.status})"])
    except McpError:
        pass
    c.table("Security checks", ["Check", "Result"], rows,
            "Safe checks only: ordinary requests, nothing attack-like. The malformed request names no tool, so no "
            "tool runs.")


def _oauth(c: Check, rows: list, url: str, reply: Reply) -> None:
    challenge = reply.headers.get("www-authenticate", "")
    meta_url = (re.search(r'resource_metadata="([^"]+)"', challenge) or [None, ""])[1] or \
        urljoin(url, "/.well-known/oauth-protected-resource")
    try:
        meta = requests.get(meta_url, timeout=15, verify=_verify())
        data = meta.json() if meta.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        data = {}
    if not data.get("authorization_servers"):
        c.problems.append("refuses callers without a login but doesn't publish where to log in "
                          "(OAuth protected resource metadata, RFC 9728)")
    rows.append(["Where to log in (OAuth metadata)", ", ".join(data.get("authorization_servers", [])) or "not found"])


def _descriptions(schema: Any) -> list[str]:
    """Every "description" (and "title") anywhere in a JSON schema."""
    if isinstance(schema, dict):
        own = [str(schema[k]) for k in ("description", "title") if isinstance(schema.get(k), str)]
        return own + [d for v in schema.values() for d in _descriptions(v)]
    if isinstance(schema, list):
        return [d for v in schema for d in _descriptions(v)]
    return []


def _safety(c: Check, tools: list[dict]) -> None:
    rows = []
    for tool in tools:
        # What the AI reads as prose: the tool's own words and every description inside its input schema. Input
        # names are left out: a login tool is meant to have a "password" input.
        text = " ".join(str(tool.get(k) or "") for k in ("name", "title", "description"))
        text += " " + " ".join(_descriptions(tool.get("inputSchema")))
        found = [why for pattern, why in HIDDEN_INSTRUCTIONS if re.search(pattern, text, re.I)]
        notes = list(found)
        ann = tool.get("annotations") or {}
        writes = bool(WRITE_WORDS.search(str(tool.get("name", ""))))
        if writes and "destructiveHint" not in ann and not ann.get("readOnlyHint"):
            notes.append("looks like it changes things but isn't marked (destructiveHint)")
        if len(tool.get("description") or "") > 2000:
            notes.append(f"very long description ({len(tool['description'])} characters)")
        c.problems += [f"{tool.get('name')}: {n}" for n in notes]
        rows.append([tool.get("name", ""), "read-only" if ann.get("readOnlyHint") else
                     "changes things" if ann.get("destructiveHint") or writes else "not marked",
                     "; ".join(notes) or "fine"])
    c.table("Tool safety", ["Tool", "Marked as", "Findings"], rows,
            "Found by looking for words; a person should still read any tool from a server they don't run.")


def _roles(c: Check, server: dict, tools: list[dict]) -> None:
    roles = server.get("roles") or []
    if not roles:
        c.not_run = "no roles in the settings (roles: name, token_env, must_not_see)"
        return
    rows = []
    for role in roles:
        token = _token(server, role.get("token_env", ""))
        if not token:
            c.problems.append(f"{role['name']}: environment variable {role.get('token_env')} is not set")
            continue
        t = _open(server, token)
        try:
            cl = Client(t)
            cl.initialize()
            seen, problems, _ = cl.list_all("tools/list", "tools")
        finally:
            t.close()
        names = {x.get("name") for x in seen}
        leaked = sorted(names & set(role.get("must_not_see") or []))
        missing = sorted(set(role.get("must_see") or []) - names)
        c.problems += [f"{role['name']} sees {n}" for n in leaked] + [f"{role['name']} can't see {n}" for n in missing]
        c.problems += [f"{role['name']}: {p}" for p in problems]
        rows.append([role["name"], len(names), ", ".join(leaked) or "none", ", ".join(missing) or "none"])
    c.table("Tools each login sees", ["Login", "Tools", "Sees but shouldn't", "Should see but can't"], rows)


def _compat(c: Check, server: dict, token: str) -> None:
    rows = []
    if server.get("command"):
        rows.append(["stdio (local command)", "works"])
    else:
        url = server["url"]
        # The older connection usually has its own address: /sse beside /mcp, or sse_url in the settings.
        sse_urls = list(dict.fromkeys(filter(None, [server.get("sse_url"), url,
                                                    url[:-4] + "/sse" if url.endswith("/mcp") else ""])))
        for kind, attempts in ((HttpTransport.kind, [("streamable", url)]),
                               (SseTransport.kind, [("sse", u) for u in sse_urls])):
            result = ""
            for transport, address in attempts:
                try:
                    t = _open({**server, "transport": transport, "url": address}, token)
                    ok = bool((Client(t).initialize().body or {}).get("result"))
                    t.close()
                    result = ("works" + (f" (at {urlparse(address).path})" if address != url else "")
                              if ok else "connects, but the handshake fails")
                    break
                except (McpError, requests.RequestException) as exc:
                    result = f"not offered ({str(exc)[:80]})"
            rows.append([kind, result])
    versions = []
    for version in PROTOCOL_VERSIONS:
        try:
            t = _open(server, token)
            reply = Client(t).initialize(version)
            t.close()
        except (McpError, requests.RequestException) as exc:
            versions.append([version, f"no answer ({str(exc)[:60]})"])
            continue
        answer = ((reply.body or {}).get("result") or {}).get("protocolVersion")
        error = ((reply.body or {}).get("error") or {}).get("message")
        versions.append([version, f"answers with {answer}" if answer else f"refused: {(error or '')[:80]}"])
    if not any(r[1].startswith("answers") for r in versions):
        c.problems.append("answers none of the protocol versions " + ", ".join(PROTOCOL_VERSIONS))
    c.table("Connection types", ["Connection", "Result"], rows,
            "The older HTTP+SSE connection is only needed for older clients.")
    c.table("Protocol versions", ["Client asks for", "Server"], versions,
            "A server that doesn't support the version asked for should answer with one it does.")


def _calls(c: Check, client: Client, server: dict, tools: list[dict]) -> None:
    wanted = server.get("call_readonly") or []
    if not wanted:
        c.not_run = "no tools listed under call_readonly (tools are never called unless you list them)"
        return
    by_name = {t.get("name"): t for t in tools}
    rows = []
    for item in wanted:
        tool = by_name.get(item.get("tool"))
        if tool is None:
            c.problems.append(f"{item.get('tool')}: not offered by the server")
            continue
        if not (tool.get("annotations") or {}).get("readOnlyHint"):
            rows.append([item["tool"], "not called: the server doesn't mark it read-only", ""])
            continue
        reply = client.call("tools/call", {"name": item["tool"], "arguments": item.get("arguments") or {}})
        result = (reply.body or {}).get("result") or {}
        error = (reply.body or {}).get("error")
        if error or result.get("isError") or not isinstance(result.get("content"), list):
            c.problems.append(f"{item['tool']}: {(error or {}).get('message') or 'the tool reported an error'}")
            rows.append([item["tool"], "error", f"{reply.ms} ms"])
        else:
            rows.append([item["tool"], f"answered ({len(result['content'])} item(s))", f"{reply.ms} ms"])
    c.table("Read-only tools called", ["Tool", "Result", "Time"], rows, "Only tools the server marks read-only "
            "are ever called, with the inputs from your settings. Their answers are not kept.")


def run(servers: list[dict], reports_dir: Path, budget_ms: int = 2000) -> tuple[int, Path]:
    """Audit each server and write a SiteSweep report. Returns (exit code, run folder)."""
    from ui_automation.cli import new_run_dir, publish_latest_report
    from ui_automation.reporting.report_html import render_summary_html
    from ui_automation.reporting.summary import RunSummary, TestResult

    started = time.monotonic()
    run_dir = new_run_dir(reports_dir)
    tests, not_run = [], []
    for server in servers:
        label = server.get("name") or server.get("url") or server.get("command")
        for check in audit(server, budget_ms):
            nodeid = f"mcp_audit::test_{check.name}[{label}]"
            if check.not_run:
                not_run.append(f"{check.name.replace('_', ' ').capitalize()} ({label}): {check.not_run}")
                continue
            failed = bool(check.problems)
            message = f"{len(check.problems)} problem(s):" if failed else ""
            details = "\n".join(f"E   - {p}" for p in check.problems)
            tests.append(TestResult(nodeid, "failed" if failed else "passed", 0.0, message=message,
                                    details=details, about=check.about, evidence=check.tables))
    passed = sum(t.outcome == "passed" for t in tests)
    failed = len(tests) - passed
    name = "MCP: " + ", ".join(str(s.get("name") or s.get("url") or s.get("command")) for s in servers)
    summary = RunSummary(exit_status=1 if failed else 0, passed=passed, failed=failed, run_dir=run_dir, tests=tests,
                         base_url=servers[0].get("url", "") if servers else "", name=name,
                         duration=time.monotonic() - started)
    (run_dir / "summary.html").write_text(render_summary_html(summary), encoding="utf-8")
    payload = summary.to_dict()
    payload["not_run"] = not_run
    (run_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    publish_latest_report(run_dir, reports_dir)
    for t in tests:
        print(f"{'PASSED' if t.outcome == 'passed' else 'FAILED'} {t.title} [{t.variant}]")
        for line in t.details.splitlines():
            print("   ", line.removeprefix("E   "))
    for line in not_run:
        print(f"NOT RUN {line}")
    print(f"{passed} passed, {failed} failed. Report: {run_dir / 'summary.html'}")
    return (1 if failed else 0), run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ui_automation.mcp_audit", description=__doc__.split("\n\n")[0])
    parser.add_argument("url", nargs="?", help="A remote MCP server, e.g. https://example.ie/mcp")
    parser.add_argument("--command", help="Or a local server started as a command (stdio)")
    parser.add_argument("--sse", action="store_true", help="The server uses the older HTTP+SSE connection")
    parser.add_argument("--token-env", default="", help="Environment variable holding the login token")
    parser.add_argument("--config", help="Or a settings file with several servers (see config/mcp.example.yaml)")
    parser.add_argument("--reports", default="reports", help="Folder for the report")
    args = parser.parse_args(argv)
    budget = 2000
    if args.config:
        import yaml

        data = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        servers = list((data.get("mcp") or {}).get("servers") or [])
        budget = int((data.get("mcp") or {}).get("budget_ms", budget))
    elif args.url or args.command:
        servers = [{"name": args.url or args.command, "url": args.url, "command": args.command,
                    "transport": "sse" if args.sse else "", "token_env": args.token_env}]
    else:
        parser.print_usage(sys.stderr)
        return 2
    bad = [s for s in servers if not s.get("command") and not str(s.get("url", "")).startswith(("http://", "https://"))]
    if not servers or bad:
        print("Each server needs a url starting with http:// or https://, or a command", file=sys.stderr)
        return 2
    code, _ = run(servers, Path(args.reports), budget)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
