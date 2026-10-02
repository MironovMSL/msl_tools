# ui/media/ffmpeg_runner.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media.ffmpeg import FfmpegTools
from msl_tools.msl.core.media.recipes import Job
from msl_tools.msl.core.media.run import Progress, ProgressParser, clean_up, error_summary, fraction, prepare


class FfmpegRunner(qt.QtCore.QObject):
    """Runs one Job (core/media/recipes.py) with ffmpeg without blocking the
    window: a QProcess per ffmpeg run, its progress read as it comes.

        runner = FfmpegRunner(parent=self)
        runner.progressed.connect(lambda done, progress: bar.setValue(int(done * 100)))
        runner.finished.connect(lambda ok, message: ...)
        runner.start(tools, job)
        ...
        runner.cancel()

    One job at a time: start() while running is refused (returns False).
    A job that fails or is cancelled leaves no half-written output behind.
    The process's input is closed and its error output is read as it comes
    — an ffmpeg left with either open can hang after its work is done.

    Signals:
        progressed(float, object) — the part of the whole job that is done
            (0..1; -1 when the job's length isn't known) and the Progress
            of the current run.
        finished(bool, str) — it is over: (True, path of the output) or
            (False, what went wrong — "Cancelled." after cancel()).
    """

    ERROR_KEPT = 20_000   # characters of ffmpeg's error output kept for the message

    progressed = qt.QtCore.Signal(float, object)
    finished = qt.QtCore.Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: qt.QtCore.QProcess | None = None
        self._tools: FfmpegTools | None = None
        self._job: Job | None = None
        self._run_index = 0
        self._parser = ProgressParser()
        self._errors = ""
        self._cancelled = False

    def is_running(self) -> bool:
        return self._job is not None

    def job(self) -> Job | None:
        return self._job

    def start(self, tools: FfmpegTools, job: Job) -> bool:
        if self._job is not None:
            return False
        self._tools, self._job = tools, job
        self._run_index, self._cancelled = 0, False
        try:
            prepare(job)  # ffmpeg doesn't create folders
        except OSError as error:
            self._end(False, f"Couldn’t create the folder for the result: {error}")
            return True
        self._start_run()
        return True

    def cancel(self) -> None:
        """Stops the job; finished(False, "Cancelled.") follows."""
        if self._process is not None and not self._cancelled:
            self._cancelled = True
            self._process.kill()

    def _start_run(self) -> None:
        command = self._job.commands(self._tools)[self._run_index]
        self._parser = ProgressParser()
        self._errors = ""
        process = qt.QtCore.QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setStandardInputFile(qt.QtCore.QProcess.nullDevice())
        process.readyReadStandardOutput.connect(self._on_output)
        process.readyReadStandardError.connect(self._on_errors)
        process.finished.connect(self._on_run_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        process.start()

    def _on_output(self) -> None:
        text = bytes(self._process.readAllStandardOutput().data()).decode("utf-8", "replace")
        for report in self._parser.feed(text):
            self.progressed.emit(fraction(self._job, self._run_index, report), report)

    def _on_errors(self) -> None:
        text = bytes(self._process.readAllStandardError().data()).decode("utf-8", "replace")
        self._errors = (self._errors + text)[-self.ERROR_KEPT:]

    def _on_process_error(self, error) -> None:
        if error == qt.QtCore.QProcess.ProcessError.FailedToStart:
            self._drop_process()
            self._end(False, "ffmpeg couldn’t be started.")

    def _on_run_finished(self, code: int, _status) -> None:
        if self._process is None:
            return  # already dealt with (failed to start)
        self._on_output()
        self._on_errors()
        self._drop_process()
        if self._cancelled:
            self._end(False, "Cancelled.")
        elif code != 0:
            self._end(False, error_summary(self._errors))
        elif self._run_index + 1 < len(self._job.passes):
            self._run_index += 1
            self._start_run()
        else:
            self.progressed.emit(1.0, Progress(done=True))
            self._end(True, str(self._job.output))

    def _drop_process(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()

    def _end(self, ok: bool, message: str) -> None:
        job, self._job = self._job, None
        clean_up(job, remove_output=not ok)
        # Always from the event loop, never from inside start(): a program that can't be
        # started fails at once, and a caller isn't ready for an answer before start() returns.
        qt.QtCore.QTimer.singleShot(0, lambda: self.finished.emit(ok, message))
