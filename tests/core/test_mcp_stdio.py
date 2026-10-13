"""core/link/mcp_stdio.py: the few MCP messages a tools-only server must answer."""
import io
import json
import unittest

from msl_tools.msl.core.link.mcp_stdio import METHOD_NOT_FOUND, StdioServer, Tool, VERSIONS


def _fail(**_arguments):
    raise ValueError("no Maya")


def _server() -> StdioServer:
    return StdioServer("test", "1.0", instructions="read me", tools=[
        Tool("echo", "says it back", lambda text="": "you said " + text,
             properties={"text": {"type": "string"}}, required=("text",)),
        Tool("fail", "always fails", _fail)])


def _call(method: str, message_id=1, **params) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "method": method, "params": params}


class Messages(unittest.TestCase):
    def test_initialize_answers_with_the_version_asked_for_when_it_is_known(self):
        result = _server().handle(_call("initialize", protocolVersion=VERSIONS[-1]))["result"]
        self.assertEqual((result["protocolVersion"], result["serverInfo"], result["instructions"]),
                         (VERSIONS[-1], {"name": "test", "version": "1.0"}, "read me"))
        self.assertIn("tools", result["capabilities"])
        newer = _server().handle(_call("initialize", protocolVersion="2099-01-01"))["result"]
        self.assertEqual(newer["protocolVersion"], VERSIONS[0])

    def test_notifications_get_no_answer(self):
        self.assertIsNone(_server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_are_listed_with_their_schema(self):
        tools = _server().handle(_call("tools/list"))["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["echo", "fail"])
        self.assertEqual(tools[0]["inputSchema"], {"type": "object", "properties": {"text": {"type": "string"}},
                                                   "required": ["text"]})

    def test_a_call_returns_text_and_drops_arguments_the_tool_does_not_have(self):
        result = _server().handle(_call("tools/call", name="echo", arguments={"text": "hi", "extra": 1}))["result"]
        self.assertEqual(result, {"content": [{"type": "text", "text": "you said hi"}], "isError": False})

    def test_a_failing_tool_is_a_result_not_a_protocol_error(self):
        result = _server().handle(_call("tools/call", name="fail"))["result"]
        self.assertEqual((result["isError"], result["content"][0]["text"]), (True, "no Maya"))

    def test_unknown_tool_and_unknown_method_are_errors(self):
        self.assertIn("error", _server().handle(_call("tools/call", name="nope")))
        self.assertEqual(_server().handle(_call("resources/list"))["error"]["code"], METHOD_NOT_FOUND)
        self.assertEqual(_server().handle(_call("ping"))["result"], {})

    def test_serve_reads_lines_and_writes_one_line_per_answer(self):
        source = io.BytesIO(b"\n".join([
            json.dumps(_call("initialize", 1)).encode(), b"not json", b"",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
            json.dumps(_call("tools/call", 2, name="echo", arguments={"text": "привет"}),
                       ensure_ascii=False).encode("utf-8")]) + b"\n")
        target = io.BytesIO()
        _server().serve(source, target)
        answers = [json.loads(line.decode("utf-8")) for line in target.getvalue().splitlines()]
        self.assertEqual([answer["id"] for answer in answers], [1, 2])
        self.assertEqual(answers[1]["result"]["content"][0]["text"], "you said привет")


if __name__ == "__main__":
    unittest.main()
