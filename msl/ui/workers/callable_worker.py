# ui/workers/callable_worker.py

import msl_tools.msl.ui.qt_bindings as qt


class CallableWorker(qt.QtCore.QThread):
    """Runs an arbitrary zero-argument callable on a background thread and
    reports its outcome back to the UI thread via signals.

    Exists so slow, blocking core calls (file I/O, network requests, install
    steps, etc.) never run directly in a Qt slot — Qt can only repaint
    widgets when it returns control to the event loop, so calling blocking
    code straight from a click handler freezes the whole window for the
    duration of the call.

    Usage:
        worker = CallableWorker(lambda: core.packageInstaller.install_package(src, dst), parent=self)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.finished_with_result.connect(self._on_finished)  # fires in both cases
        worker.start()

    Contains no domain logic and no progress reporting of its own — pair it
    with BaseProgressBar.set_indeterminate(True/False) if the caller doesn't
    have a real percentage to show, since a fabricated percentage that
    doesn't track actual work is misleading.
    """

    # Fires once, after the callable returns, regardless of outcome.
    # Payload is the bool-coerced return value (False if an exception was raised).
    finished_with_result = qt.QtCore.Signal(bool)

    # Fires only when the callable completed without raising and returned a truthy value.
    succeeded = qt.QtCore.Signal()

    # Fires only when the callable raised, or returned a falsy value.
    # `error` is the caught exception, or None if it simply returned False/None/[]/etc.
    failed = qt.QtCore.Signal(object)

    def __init__(self, target, parent=None):
        """
        Args:
            target: Zero-argument callable to run on the background thread.
                Its return value is coerced with bool(); anything falsy is
                treated as failure. Exceptions are caught and reported via
                `failed` instead of propagating out of the thread.
            parent: Optional QObject parent.
        """
        super().__init__(parent)
        self._target = target

    def run(self) -> None:
        error = None
        try:
            result = bool(self._target())
        except Exception as e:
            result = False
            error = e

        if result:
            self.succeeded.emit()
        else:
            self.failed.emit(error)

        self.finished_with_result.emit(result)


if __name__ == "__main__":
    import time
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    def _fake_slow_success() -> bool:
        time.sleep(1)
        return True

    def _fake_slow_failure() -> bool:
        time.sleep(1)
        raise RuntimeError("boom")

    with QtApplicationContext():
        worker = CallableWorker(_fake_slow_success)
        worker.finished_with_result.connect(lambda ok: print(f"finished_with_result: {ok}"))
        worker.succeeded.connect(lambda: print("succeeded"))
        worker.failed.connect(lambda err: print(f"failed: {err}"))
        worker.start()
        worker.wait()