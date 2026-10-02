# core/link/protocol.py
"""Wire format of the hub <-> Maya link — shared by both ends, Qt-free.

A message is a JSON object, sent as

    <10 ASCII digits: the body's size in bytes><body: the JSON, UTF-8>

The size header lets the receiver cut a TCP stream back into messages of any
length (a stream has no message boundaries of its own).

Three kinds of message, told apart by "type":

    {"type": "event",   "name": "scene", "data": {...}}              one way, no answer expected
    {"type": "request", "name": "ping",  "id": 7, "data": {...}}     expects a reply with the same id
    {"type": "reply",   "id": 7, "success": true, "data": {...}}     (or "success": false, "error": "...")

The id is what keeps answers matched to questions when one side is slow —
without it a late reply would be taken for the answer to the next request.

This module runs inside Maya too (2023: Python 3.9), so: standard library
only, and no syntax newer than 3.9 at runtime.
"""
from __future__ import annotations

import json

HEADER_SIZE = 10
MAX_BODY_SIZE = 8 * 1024 * 1024  # a message announcing more than this is garbage, not a message

EVENT, REQUEST, REPLY = "event", "request", "reply"

# Message names.
HELLO = "hello"      # event, Maya -> hub, first message: who am I (with the token)
SCENE = "scene"      # event, Maya -> hub: the open scene changed
PING = "ping"        # request, either way
# Requests hub -> Maya (handled in tools/maya/hub_link.py; replies carry the result in "data"):
LAUNCH_REPORT = "launch_report"   # -> {"text": the launch report}
RELOAD_CODE = "reload_code"       # -> {"modules": how many msl_tools modules were dropped}
PLUGIN_STATE = "plugin_state"     # {"names": [...]} -> {"loaded": [those of them that are loaded]}
LOAD_PLUGINS = "load_plugins"     # {"names": [...]} -> {"loaded": [...], "failed": {name: why}}


class ProtocolError(Exception):
    """The peer sent something that isn't a message (bad header, bad JSON, too large)."""


def encode(message: dict) -> bytes:
    """`message` as bytes ready to send."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_BODY_SIZE:
        raise ProtocolError("message too large: %d bytes" % len(body))
    return ("%0*d" % (HEADER_SIZE, len(body))).encode("ascii") + body


def event(name: str, **data) -> dict:
    return {"type": EVENT, "name": name, "data": data}


def request(name: str, message_id: int, **data) -> dict:
    return {"type": REQUEST, "name": name, "id": message_id, "data": data}


def reply(message_id: int, success: bool = True, error: str = "", **data) -> dict:
    message = {"type": REPLY, "id": message_id, "success": bool(success), "data": data}
    if error:
        message["error"] = error
    return message


class FrameDecoder:
    """Cuts a byte stream into messages. Feed it whatever arrived; it keeps
    an incomplete tail until the rest comes."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        """Adds `data` and returns every message now complete (maybe none).

        Raises:
            ProtocolError: the stream doesn't hold valid messages — the
                connection can't be trusted to be in step anymore; drop it.
        """
        self._buffer += data
        messages: list[dict] = []
        while len(self._buffer) >= HEADER_SIZE:
            header = bytes(self._buffer[:HEADER_SIZE])
            if not header.isdigit():
                raise ProtocolError("bad header: %r" % header)
            size = int(header)
            if size > MAX_BODY_SIZE:
                raise ProtocolError("message too large: %d bytes" % size)
            if len(self._buffer) < HEADER_SIZE + size:
                break  # the body hasn't fully arrived yet
            body = bytes(self._buffer[HEADER_SIZE:HEADER_SIZE + size])
            del self._buffer[:HEADER_SIZE + size]
            try:
                message = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise ProtocolError("bad body: %s" % error)
            if not isinstance(message, dict):
                raise ProtocolError("a message must be a JSON object")
            messages.append(message)
        return messages
