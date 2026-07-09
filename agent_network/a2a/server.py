"""
HTTP server that receives agent-to-agent messages and routes them to the
local twin. This makes A2A *real network communication*: a twin running as
one service can message a twin running as another service.

Stdlib-only (http.server) so it runs without extra dependencies.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_network.models import AgentMessage
from agent_network.runtime import get_runtime

logger = logging.getLogger(__name__)


def handle_a2a_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate an incoming AgentMessage and deliver it to the local recipient twin.
    Returns an ack dict. Framework-agnostic so it can be hosted by any web layer.
    """
    try:
        message = AgentMessage.model_validate(payload)
    except Exception as e:
        return {"accepted": False, "error": f"invalid message: {e}"}

    bus, twins = get_runtime()
    recipient = message.recipient_agent_id
    emp_id = recipient[len("twin-"):] if recipient.startswith("twin-") else recipient
    twin = twins.get(emp_id)
    if not twin:
        return {"accepted": False, "error": f"unknown recipient: {recipient}"}

    bus.send(message)
    logger.info(
        "A2A delivered %s -> %s (%s)",
        message.sender_agent_id,
        recipient,
        message.message_type.value,
    )
    return {
        "accepted": True,
        "message_id": message.message_id,
        "recipient": recipient,
        "message_type": message.message_type.value,
    }


class _A2AHandler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/healthz", "/health"):
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/api/a2a", "/a2a"):
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        result = handle_a2a_request(payload)
        self._json(200 if result.get("accepted") else 400, result)

    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        return


def run_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), _A2AHandler)
    logger.info("A2A server listening on http://%s:%d/api/a2a", host, port)
    print(f"A2A server listening on http://{host}:{port}/api/a2a (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
