# ui/workers/result_worker.py
import msl_tools.msl.ui.qt_bindings as qt


class ResultWorker(qt.QtCore.QThread):
    """Runs a zero-argument callable on a background thread and hands its
    RESULT back to the UI thread (CallableWorker only says whether it worked).

        worker = ResultWorker(lambda: probe(tools, path), parent=self)
        worker.done.connect(self._on_info)        # the callable's return value
        worker.failed.connect(self._on_error)     # the exception it raised
        worker.start()

    Keep a reference to the worker (or give it a parent) until it is over.
    When the application quits while it runs, it is waited for (up to
    QUIT_WAIT_MS): a QThread destroyed while running takes the process down.

    Signals:
        done(object) — the callable returned; carries what it returned.
        failed(object) — the callable raised; carries the exception.
    """

    done = qt.QtCore.Signal(object)
    failed = qt.QtCore.Signal(object)

    QUIT_WAIT_MS = 5000

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self._target = target
        application = qt.QtCore.QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._wait_on_quit)

    def _wait_on_quit(self) -> None:
        if self.isRunning():
            self.wait(self.QUIT_WAIT_MS)

    def run(self) -> None:
        try:
            result = self._target()
        except Exception as error:
            self.failed.emit(error)
        else:
            self.done.emit(result)
