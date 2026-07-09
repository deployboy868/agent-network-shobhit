"""Minimal MCP stdio transport (JSON-RPC 2.0 + Content-Length framing)."""

from __future__ import annotations

import json
from typing import Any, BinaryIO, Optional


def read_message(stream: BinaryIO) -> Optional[dict[str, Any]]:
    """Read one MCP message from stdin. Returns None only on EOF."""
    while True:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                return None
            line = line.decode("utf-8").strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        length = int(headers.get("content-length", "0"))
        if length <= 0:
            continue

        body = stream.read(length)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            continue


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    stream.write(data)
    stream.flush()


def write_response(stream: BinaryIO, req_id: Any, result: Any) -> None:
    write_message(stream, {"jsonrpc": "2.0", "id": req_id, "result": result})


def write_error(stream: BinaryIO, req_id: Any, code: int, message: str) -> None:
    write_message(
        stream,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        },
    )
