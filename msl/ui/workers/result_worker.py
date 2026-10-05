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
    A worker WITH a parent deletes itself once finished: drop the reference
    in a `finished` handler and don't touch it afterwards.
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
        if parent is not None:
            # Over = gone: a parented worker would otherwise live (a QThread each) until its
            # parent dies — Media made one per estimate, picture and thumbnail. The delete is
            # deferred, so the owner's own `finished` handlers still run first. Parentless
            # workers (the Playblast panel's, kept by the class) are left to their owner.
            self.finished.connect(self.deleteLater)
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


def run_in_background(target, on_done=None, on_failed=None, *, keep, parent=None) -> ResultWorker:
    """Starts `target` on a ResultWorker and returns it — the one way the tools start one.

    keep: the owner's list or set the worker is held in while it runs (removed when it is over).
        A parentless worker must be held somewhere: a QThread destroyed while running takes the
        process down. The Playblast panel keeps a CLASS-level set (a panel can be deleted any
        moment inside Maya); hub pages keep a list of their own and pass `parent=`.
    on_done(result) / on_failed(error): connected before the start; a parented worker deletes
        itself after them. Prefer bound methods for parentless workers: a lambda holding a widget
        keeps calling into it after it is gone.
    """
    worker = ResultWorker(target, parent=parent)
    add = getattr(keep, "add", None) or keep.append
    add(worker)

    def over() -> None:
        if worker in keep:
            keep.remove(worker)

    if on_done is not None:
        worker.done.connect(on_done)
    if on_failed is not None:
        worker.failed.connect(on_failed)
    worker.finished.connect(over)
    worker.start()
    return worker
