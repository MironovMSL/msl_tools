# tools/maya/hub_link.py
"""Maya's end of the hub <-> Maya link: connects this Maya session to the
MSL Tools hub that launched it, and keeps the hub told about it.

The hub listens (ui/maya_link/server.py); this client connects, says hello
(which Maya, which environment, which scene) and then reports scene changes
and what the Script Editor prints — warnings and errors, and plain messages
too once the hub asks for them.
If the hub isn't there — closed, restarting — it quietly tries again every
few seconds, so a restarted hub gets its running Mayas back.

Started by Maya Gate's loader (tools/desktop/maya_gate/boost.py) in every
Maya launched from the hub, with the address in environment variables:
MSL_GATE_LINK_PORT, MSL_GATE_LINK_TOKEN.

Everything runs in Maya's main thread through Qt signals: no thread of our
own, nothing blocks, and whatever a later version does on a request from
the hub may call maya.cmds safely.

NOT through the project's Qt shim (ui/qt_bindings.py), on purpose: this has
to work in every Maya that can import msl_tools — Maya 2023 / 2024 ship
PySide2, the shim is PySide6-only. For the same reason: no syntax newer
than Python 3.9 at runtime.
"""
from __future__ import annotations

import os
import sys

try:
    from PySide6 import QtCore, QtNetwork, QtWidgets
except ImportError:  # Maya 2023 / 2024
    from PySide2 import QtCore, QtNetwork, QtWidgets

from msl_tools.msl import __version__ as _msl_version
from msl_tools.msl.core.link import protocol

PORT_VARIABLE = "MSL_GATE_LINK_PORT"
TOKEN_VARIABLE = "MSL_GATE_LINK_TOKEN"
ENVIRONMENT_VARIABLE = "MSL_GATE_ENVIRONMENT"
BOOST_VARIABLE = "MSL_GATE_BOOST_SKIP"
OBJECT_NAME = "mslHubLink"


class HubLink(QtCore.QObject):
    """The connection to the hub. One per Maya session (see start())."""

    RECONNECT_MS = 5000
    SCENE_EVENTS = ("SceneOpened", "NewSceneOpened", "SceneSaved")
    LOG_FLUSH_MS = 250       # Script Editor output goes out in batches, not line by line
    LOG_BUFFER_MAX = 400     # lines kept between two flushes (and while the hub is away)
    LOG_TEXT_MAX = 6000      # characters of one message

    def __init__(self, port: int, token: str, parent=None):
        super().__init__(parent)
        self.setObjectName(OBJECT_NAME)
        self._port = port
        self._token = token
        self._decoder = protocol.FrameDecoder()
        self._script_jobs: list[int] = []
        self._sent_scene: str | None = None  # the scene the hub was last told about
        self._log_all = False                # False: warnings and errors only
        self._log_buffer: list[list[str]] = []
        self._log_dropped = 0
        self._output_callback = None
        self._log_levels: dict = {}

        self._log_timer = QtCore.QTimer(self)
        self._log_timer.setInterval(self.LOG_FLUSH_MS)
        self._log_timer.timeout.connect(self._flush_log)

        self._socket = QtNetwork.QTcpSocket(self)
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.readyRead.connect(self._on_ready_read)
        self._socket.errorOccurred.connect(self._on_error)

        self._retry = QtCore.QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(self.RECONNECT_MS)
        self._retry.timeout.connect(self._connect)

    # --- life cycle --------------------------------------------------------------

    def open(self) -> None:
        self._watch_scene()
        self._watch_output()
        self._log_timer.start()
        self._connect()

    def shut(self) -> None:
        """Stops for good (a newer HubLink replaces this one)."""
        import maya.cmds as cmds
        self._retry.stop()
        for job in self._script_jobs:
            try:
                if cmds.scriptJob(exists=job):
                    cmds.scriptJob(kill=job, force=True)
            except Exception:
                pass
        self._script_jobs = []
        self._log_timer.stop()
        if self._output_callback is not None:
            try:
                import maya.api.OpenMaya as om
                om.MMessage.removeCallback(self._output_callback)
            except Exception:
                pass
            self._output_callback = None
        self._socket.abort()

    def is_connected(self) -> bool:
        return self._socket.state() == QtNetwork.QAbstractSocket.SocketState.ConnectedState

    def _connect(self) -> None:
        if self._socket.state() == QtNetwork.QAbstractSocket.SocketState.UnconnectedState:
            self._decoder = protocol.FrameDecoder()
            self._socket.connectToHost("127.0.0.1", self._port)

    def _on_error(self, _error) -> None:
        # Refused (no hub), dropped, ... - whatever it was, try again later.
        if not self.is_connected() and not self._retry.isActive():
            self._retry.start()

    def _on_disconnected(self) -> None:
        if not self._retry.isActive():
            self._retry.start()

    # --- messages ------------------------------------------------------------------

    def _send(self, message: dict) -> None:
        if self.is_connected():
            self._socket.write(protocol.encode(message))

    def _on_connected(self) -> None:
        import maya.cmds as cmds
        try:
            # "Autodesk MAYA 2025.3.1" -> "2025.3.1"
            full_version = str(cmds.about(installedVersion=True)).split()[-1]
        except Exception:
            full_version = ""
        self._sent_scene = self._scene()
        # A fresh connection starts on "warnings and errors only": the hub that
        # wants more says so again (it may be a different, restarted hub).
        self._log_all = False
        self._send(protocol.event(
            protocol.HELLO,
            token=self._token,
            pid=os.getpid(),
            version=str(cmds.about(version=True)),
            full_version=full_version,
            environment=os.environ.get(ENVIRONMENT_VARIABLE, ""),
            boosted=BOOST_VARIABLE in os.environ,
            skipped=[name for name in os.environ.get(BOOST_VARIABLE, "").split(os.pathsep) if name],
            scene=self._sent_scene,
            msl_version=_msl_version))

    def _on_ready_read(self) -> None:
        try:
            messages = self._decoder.feed(bytes(self._socket.readAll().data()))
        except protocol.ProtocolError:
            self._socket.abort()
            return
        for message in messages:
            if message.get("type") == protocol.REQUEST:
                self._on_request(message)

    def _on_request(self, message: dict) -> None:
        """Requests from the hub: a FIXED list (_HANDLERS) — a name that isn't
        on it is refused; nothing that arrives is executed as code. A handler
        runs here, in Maya's main thread, and its result is the reply; an
        exception becomes a failure reply, never an error in Maya."""
        name, message_id = message.get("name"), message.get("id", 0)
        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        handler = self._HANDLERS.get(name)
        if handler is None:
            self._send(protocol.reply(message_id, success=False, error="unknown request: %s" % name))
            return
        try:
            result = handler(self, data) or {}
        except Exception as error:
            self._send(protocol.reply(message_id, success=False, error="%s: %s" % (type(error).__name__, error)))
            return
        self._send(protocol.reply(message_id, **result))
        self._socket.flush()

    # --- the Script Editor's output --------------------------------------------------------

    def _watch_output(self) -> None:
        """Has Maya call _on_output for everything it prints to the Script Editor."""
        try:
            import maya.api.OpenMaya as om
            kinds = om.MCommandMessage
            self._log_levels = {kinds.kError: protocol.LOG_ERROR, kinds.kWarning: protocol.LOG_WARNING,
                                kinds.kStackTrace: protocol.LOG_TRACE, kinds.kInfo: protocol.LOG_INFO,
                                kinds.kResult: protocol.LOG_INFO, kinds.kDisplay: protocol.LOG_INFO}
            self._output_callback = kinds.addCommandOutputCallback(self._on_output)
        except Exception:
            self._output_callback = None

    def _on_output(self, message, kind, _client_data=None) -> None:
        """Maya printed `message`. Called for EVERY line of output, so: quick,
        and never printing or raising itself (that would come straight back
        here). Command echo (history) is never forwarded; plain messages only
        when the hub asked for everything. Lines are only collected here —
        _flush_log() sends them."""
        try:
            level = self._log_levels.get(kind)
            if level is None or (level == protocol.LOG_INFO and not self._log_all):
                return
            text = str(message).rstrip()
            if not text:
                return
            if len(self._log_buffer) >= self.LOG_BUFFER_MAX:
                self._log_dropped += 1
                return
            self._log_buffer.append([level, text[:self.LOG_TEXT_MAX]])
        except Exception:
            pass

    def _flush_log(self) -> None:
        if not self._log_buffer or not self.is_connected():
            return
        entries, dropped = self._log_buffer, self._log_dropped
        self._log_buffer, self._log_dropped = [], 0
        self._send(protocol.event(protocol.LOG, entries=entries, dropped=dropped))

    def _handle_set_log_level(self, data: dict) -> dict:
        self._log_all = bool(data.get("all"))
        return {"all": self._log_all}

    # --- what the hub may ask for --------------------------------------------------------

    def _handle_ping(self, _data: dict) -> dict:
        return {}

    def _handle_launch_report(self, _data: dict) -> dict:
        from msl_tools.msl.tools.maya.launch_report import build_launch_report
        return {"text": build_launch_report()}

    def _handle_reload_code(self, _data: dict) -> dict:
        """Drops msl_tools from sys.modules (the next import reads the files
        again), rebuilds the MSL menu if this Maya has one, and restarts
        this link on the new code — after the reply went out."""
        removed = [name for name in list(sys.modules) if name == "msl_tools" or name.startswith("msl_tools.")]
        for name in removed:
            del sys.modules[name]
        menu = False
        try:
            import maya.cmds as cmds
            if cmds.menu("MSLToolsMenu", exists=True):  # rebuild the menu only where there is one
                from msl_tools.msl.startup import rebuild_menu
                menu = bool(rebuild_menu())
        except Exception:
            menu = False  # e.g. Maya 2023: the menu needs Python 3.10
        QtCore.QTimer.singleShot(300, _restart_on_fresh_code)
        return {"modules": len(removed), "menu": menu}

    def _handle_plugin_state(self, data: dict) -> dict:
        import maya.cmds as cmds
        loaded = []
        for name in data.get("names") or []:
            try:
                if cmds.pluginInfo(str(name), query=True, loaded=True):
                    loaded.append(name)
            except Exception:
                pass
        return {"loaded": loaded}

    def _handle_load_plugins(self, data: dict) -> dict:
        import maya.cmds as cmds
        loaded, failed = [], {}
        for name in data.get("names") or []:
            name = str(name)
            try:
                if not cmds.pluginInfo(name, query=True, loaded=True):
                    cmds.loadPlugin(name, quiet=True)
                loaded.append(name)
            except Exception as error:
                failed[name] = str(error).strip()
        return {"loaded": loaded, "failed": failed}

    _HANDLERS = {
        protocol.PING: _handle_ping,
        protocol.LAUNCH_REPORT: _handle_launch_report,
        protocol.RELOAD_CODE: _handle_reload_code,
        protocol.PLUGIN_STATE: _handle_plugin_state,
        protocol.LOAD_PLUGINS: _handle_load_plugins,
        protocol.SET_LOG_LEVEL: _handle_set_log_level,
    }

    # --- the scene ---------------------------------------------------------------------

    @staticmethod
    def _scene() -> str:
        import maya.cmds as cmds
        try:
            return str(cmds.file(query=True, sceneName=True) or "")
        except Exception:
            return ""

    def _watch_scene(self) -> None:
        import maya.cmds as cmds
        for name in self.SCENE_EVENTS:
            try:
                self._script_jobs.append(cmds.scriptJob(event=[name, self._on_scene_changed], protected=True))
            except Exception:
                pass

    def _on_scene_changed(self) -> None:
        scene = self._scene()
        if scene != self._sent_scene:  # new + rename + save fire several events for one change
            self._sent_scene = scene
            self._send(protocol.event(protocol.SCENE, scene=scene))


def current() -> HubLink | None:
    """This Maya session's link, if one was started."""
    application = QtWidgets.QApplication.instance()
    return application.findChild(QtCore.QObject, OBJECT_NAME) if application is not None else None


def start() -> bool:
    """Connects this Maya to the hub named by the environment variables.
    Safe to call again (a previous link is replaced). Returns False when
    this Maya wasn't started from the hub, or isn't an interactive one."""
    port, token = os.environ.get(PORT_VARIABLE, ""), os.environ.get(TOKEN_VARIABLE, "")
    application = QtWidgets.QApplication.instance()
    if not port.isdigit() or not token or application is None:
        return False
    stop()
    # Owned by the QApplication, so it outlives this module being reloaded
    # (the MSL menu's "Reload Code" drops msl_tools from sys.modules).
    link = HubLink(int(port), token, parent=application)
    link.open()
    return True


def _restart_on_fresh_code() -> None:
    """After "reload code": the running link is still the OLD class — replace
    it with one from the freshly imported module."""
    try:
        from msl_tools.msl.tools.maya import hub_link as fresh
        fresh.start()
    except Exception:
        import traceback
        traceback.print_exc()


def stop() -> None:
    link = current()
    if link is not None:
        try:
            link.shut()
        finally:
            link.setObjectName("")
            link.deleteLater()
