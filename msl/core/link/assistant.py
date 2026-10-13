# core/link/assistant.py
"""The assistant's side door into the hub — Qt-free: what it may ask, the
log the hub keeps for it, and a small blocking client.

An assistant (an MCP server started by a coding assistant) does not talk to
Maya. It asks the HUB, over a second local channel
(ui/maya_link/assistant_server.py), and the hub answers from what it knows
or passes the question on over the hub <-> Maya link it already has. The
channel is off until the user switches it on, listens on 127.0.0.1 only and
has a token of its own — not the one Mayas are given.

Wire format and handshake are the hub <-> Maya link's (protocol.py): the
client plays Maya's part (hello with a nonce, then its proof), so the token
never goes over the wire and each side proves itself first.

Requests (assistant -> hub):

    sessions   {}                                  -> {"sessions": [session, ...]}
    read_log   {"pid", "after", "limit", "levels"} -> {"entries": [entry, ...], "last": seq, "known": bool}
    run_python {"pid", "code", "seconds"}          -> {"output", "result", "traceback"}

run_python is the one request that carries code. The hub passes it to that
Maya as the Sessions tab's console would (protocol.RUN_PYTHON) - only while
the user allowed code for the assistant, and Maya itself still decides
whether it takes code at all. `seconds` is how long the hub waits for Maya.

A session is described by `describe()`; an entry is {"seq", "time", "level",
"text"}. `after` is the last `seq` already read (0 = from the start of what
is kept), so reading again returns only what came since.
"""
from __future__ import annotations

import json
import socket
import time
from collections import OrderedDict, deque

from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.link.session import MayaSession

CONFIG_NAME = "maya_assistant"   # configs/desktop/maya_assistant/config.json: port, token, enabled
DEFAULT_PORT = 47631
ROLE = "assistant"               # the hello's "role"

SESSIONS = "sessions"
READ_LOG = "read_log"
RUN_PYTHON = "run_python"
REQUESTS = (SESSIONS, READ_LOG, RUN_PYTHON)

MAX_READ = 500                   # entries one read_log may return
MAX_CODE = 1024 * 1024           # characters of code one run_python may carry
RUN_SECONDS = (5, 600)           # how long a run_python may ask the hub to wait for Maya: least, most
RUN_SECONDS_DEFAULT = 60


def describe(session: MayaSession, problems: tuple[int, int] = (0, 0), now: float | None = None) -> dict:
    """`session` as plain data for the assistant. `problems` = (errors, warnings) its log holds."""
    now = time.time() if now is None else now
    return {"pid": session.pid, "version": session.version, "environment": session.environment,
            "scene": session.scene, "modified": session.modified, "busy": session.busy,
            "boosted": session.boosted, "console": session.console, "msl_version": session.msl_version,
            "connected_seconds": int(max(now - session.connected_at, 0)),
            "errors": problems[0], "warnings": problems[1]}


class LogBook:
    """What each Maya's Script Editor reported, kept for the assistant to read.

    Keyed by Maya's PID (a session's id changes on "Reload code"). The last
    PER_MAYA entries of each of the last MAYAS Mayas are kept — also of one
    that is gone: a crashed Maya's log is the one that is wanted.
    """

    PER_MAYA = 2000
    MAYAS = 8

    def __init__(self) -> None:
        self._logs: OrderedDict[int, deque] = OrderedDict()
        self._last: dict[int, int] = {}   # pid -> the seq given out last

    def add(self, pid: int, entries, now: float | None = None) -> None:
        """Appends `entries` ([(level, text), ...]) to Maya `pid`'s log."""
        now = time.time() if now is None else now
        log = self._logs.get(pid)
        if log is None:
            log = self._logs[pid] = deque(maxlen=self.PER_MAYA)
            while len(self._logs) > self.MAYAS:
                gone, _ = self._logs.popitem(last=False)
                self._last.pop(gone, None)
        self._logs.move_to_end(pid)
        seq = self._last.get(pid, 0)
        for level, text in entries:
            seq += 1
            log.append({"seq": seq, "time": now, "level": level, "text": text})
        self._last[pid] = seq

    def knows(self, pid: int) -> bool:
        return pid in self._logs

    def problems(self, pid: int) -> tuple[int, int]:
        """(errors, warnings) among Maya `pid`'s kept entries."""
        log = self._logs.get(pid, ())
        return (sum(1 for entry in log if entry["level"] == protocol.LOG_ERROR),
                sum(1 for entry in log if entry["level"] == protocol.LOG_WARNING))

    def read(self, pid: int, after: int = 0, limit: int = 200, levels=None) -> tuple[list[dict], int]:
        """Maya `pid`'s entries with seq > `after` — the NEWEST `limit` of
        them, oldest first — and the last seq given out (pass it as the next
        `after`). `levels` narrows to those levels."""
        limit = max(1, min(int(limit), MAX_READ))
        wanted = set(levels) if levels else None
        found = [entry for entry in self._logs.get(pid, ())
                 if entry["seq"] > after and (wanted is None or entry["level"] in wanted)]
        return found[-limit:], self._last.get(pid, 0)


class AssistantError(Exception):
    """The hub can't be asked, or refused. The message is written for the person reading it."""


def read_address(config_file) -> tuple[int, str, bool]:
    """(port, token, enabled) from the hub's config file — read, never written (the hub owns it)."""
    try:
        with open(config_file, encoding="utf-8") as handle:
            data = json.load(handle)
        return int(data.get("port") or 0), str(data.get("token") or ""), bool(data.get("enabled"))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0, "", False


class AssistantClient:
    """One connection to the hub's assistant channel, on a plain blocking socket.

    `request()` connects on first use and again after the hub went away, so
    one client serves a long-lived MCP server across hub restarts.
    """

    def __init__(self, port: int, token: str, timeout: float = 5.0):
        self.port, self.token, self.timeout = port, token, timeout
        self._socket: socket.socket | None = None
        self._decoder = protocol.FrameDecoder()
        self._inbox: list[dict] = []   # messages that arrived and were not asked for yet
        self._next_id = 1

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None

    def connect(self) -> None:
        """Connects and proves itself, having checked the hub's proof first.

        Raises:
            AssistantError: nothing listens there, or what does isn't the hub.
        """
        self.close()
        self._decoder, self._inbox = protocol.FrameDecoder(), []
        try:
            self._socket = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
            nonce = protocol.new_nonce()
            self._send(protocol.event(protocol.HELLO, role=ROLE, nonce=nonce))
            welcome = self._receive()
            data = welcome.get("data") if isinstance(welcome.get("data"), dict) else {}
            hub_nonce = data.get("nonce")
            if (welcome.get("name") != protocol.WELCOME or not protocol.is_nonce(hub_nonce) or not
                    protocol.same_secret(protocol.hub_proof(self.token, nonce, hub_nonce), data.get("proof"))):
                raise AssistantError("What answers on the hub’s port did not prove it is MSL Tools.")
            self._send(protocol.event(protocol.PROOF, proof=protocol.maya_proof(self.token, nonce, hub_nonce)))
        except AssistantError:
            self.close()
            raise
        except (OSError, protocol.ProtocolError) as error:
            self.close()
            raise AssistantError("MSL Tools can’t be reached (is it running, with the assistant "
                                 "access switched on?): %s" % error)

    def request(self, name: str, wait: float | None = None, again: bool = True, **data) -> dict:
        """Asks the hub `name` and returns the reply's data.

        Args:
            wait: seconds to wait for the answer (None = the client's timeout).
            again: ask once more if the connection turns out to be gone. Pass
                False for a request that must not be done twice (run_python:
                the first one may have reached Maya before the line broke).

        Raises:
            AssistantError: the hub can't be reached, or answered with a failure.
        """
        for attempt in (1, 2):   # a connection the hub closed since is noticed only on use
            if self._socket is None:
                self.connect()
            self._socket.settimeout(self.timeout if wait is None else wait)
            request_id = self._next_id
            self._next_id += 1
            try:
                self._send(protocol.request(name, request_id, **data))
                while True:
                    message = self._receive()
                    if message.get("type") == protocol.REPLY and message.get("id") == request_id:
                        break
            except (OSError, protocol.ProtocolError, AssistantError) as error:
                self.close()
                if attempt == 2 or not again:
                    raise AssistantError("MSL Tools stopped answering: %s" % error)
                continue
            if not message.get("success"):
                raise AssistantError(str(message.get("error") or "MSL Tools refused the request."))
            return message.get("data") if isinstance(message.get("data"), dict) else {}
        raise AssistantError("MSL Tools can’t be reached.")

    def _send(self, message: dict) -> None:
        self._socket.sendall(protocol.encode(message))

    def _receive(self) -> dict:
        while not self._inbox:
            data = self._socket.recv(65536)
            if not data:
                raise AssistantError("the connection was closed")
            self._inbox += self._decoder.feed(data)
        return self._inbox.pop(0)
