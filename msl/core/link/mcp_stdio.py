# core/link/mcp_stdio.py
"""A minimal MCP server over stdio — standard library only.

MCP (Model Context Protocol) is how a coding assistant is given tools. Over
stdio it is JSON-RPC 2.0, one message per line: the assistant starts this
process, asks `initialize`, `tools/list`, then `tools/call` whenever it uses
a tool. Only that part is here — tools, no resources or prompts — which is
why no package is needed for it.

A tool is a function taking the call's arguments as keywords and returning
text; an exception it raises becomes the tool's error text (isError), which
the assistant reads — it is not a protocol failure.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Callable

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")   # protocol revisions this speaks, newest first

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


@dataclass
class Tool:
    """One tool: its name, what it is for (the assistant reads this to decide
    when to use it), its arguments as JSON Schema properties, and the function."""

    name: str
    description: str
    function: Callable[..., str]
    properties: dict = field(default_factory=dict)
    required: tuple = ()

    def listing(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": {"type": "object", "properties": self.properties, "required": list(self.required)}}


class StdioServer:
    """Answers MCP messages for a fixed list of tools."""

    def __init__(self, name: str, version: str, tools: list[Tool], instructions: str = ""):
        self.name, self.version, self.instructions = name, version, instructions
        self.tools = {tool.name: tool for tool in tools}

    def handle(self, message: dict) -> dict | None:
        """The answer to `message`, or None when it expects none (a notification)."""
        method, message_id = message.get("method"), message.get("id")
        if message_id is None or not isinstance(method, str):
            return None   # a notification, or a reply to something this never asks
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": self.name, "version": self.version}}
            if self.instructions:
                result["instructions"] = self.instructions
            return self._result(message_id, result)
        if method == "ping":
            return self._result(message_id, {})
        if method == "tools/list":
            return self._result(message_id, {"tools": [tool.listing() for tool in self.tools.values()]})
        if method == "tools/call":
            tool = self.tools.get(params.get("name"))
            if tool is None:
                return self._error(message_id, INVALID_PARAMS, "Unknown tool: %s" % params.get("name"))
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            arguments = {key: value for key, value in arguments.items() if key in tool.properties}
            try:
                text, failed = str(tool.function(**arguments)), False
            except Exception as error:  # the tool's own failure: told to the assistant as its result
                text, failed = str(error) or type(error).__name__, True
            return self._result(message_id, {"content": [{"type": "text", "text": text}], "isError": failed})
        return self._error(message_id, METHOD_NOT_FOUND, "Method not found: %s" % method)

    @staticmethod
    def _result(message_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error(message_id, code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}

    def serve(self, source=None, target=None) -> None:
        """Reads messages from stdin and answers on stdout until stdin closes.
        Bytes, UTF-8, "\\n" between messages — never the console's own encoding
        or line ends; nothing else may be written to stdout while this runs."""
        source = source if source is not None else sys.stdin.buffer
        target = target if target is not None else sys.stdout.buffer
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if not isinstance(message, dict):
                continue
            answer = self.handle(message)
            if answer is not None:
                target.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
                target.flush()
