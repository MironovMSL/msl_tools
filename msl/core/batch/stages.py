"""Where a render job stands, as steps for the CURRENT RENDER card's StepTrack: Read -> Open ->
Render (-> Video). Qt-free: the job and whether its video is being made in, (step, state) out.

States are the StepTrack's words: "waiting" (nothing at work on it now), "running", "error",
"done" (every step done).
"""
from .job import CANCELLED, CHECKING, DONE, FAILED, RUNNING, BatchJob

READ, OPEN, RENDER, VIDEO = "Read", "Open", "Render", "Video"

# Maya's own words before the first frame: it is starting / opening the scene
_OPENING = ("starting", "the scene", "opening", "loading")


def steps_of(job: BatchJob) -> list[str]:
    """The job's steps: the video only when it makes one."""
    return [READ, OPEN, RENDER] + ([VIDEO] if job.make_video else [])


def stage_of(job: BatchJob, making_video: bool = False) -> tuple[int, str]:
    """(index of the step at hand, state) for `job`; (len(steps), "done") when all is done."""
    steps = steps_of(job)
    message = (job.message or "").lower()
    rendering = bool(job.done) or message.startswith(("frame", "rendering"))
    if making_video and job.make_video:
        return steps.index(VIDEO), "running"
    if job.state == CHECKING:
        return 0, "running"
    if job.state == RUNNING:
        return (2, "running") if rendering and not message.startswith(_OPENING) else (1, "running")
    if job.state == DONE:
        if job.make_video and not job.video:
            failed = "no video" in message or "video failed" in message
            return steps.index(VIDEO), "error" if failed else "waiting"
        return len(steps), "done"
    if job.state in (FAILED, CANCELLED):
        state = "error" if job.state == FAILED else "waiting"
        if not job.probe:
            return 0, state
        return (2 if job.done else 1), state
    # waiting: read already = it waits to be opened (or to go on where it stopped)
    if not job.probe:
        return 0, "waiting"
    return (2 if job.done else 1), "waiting"
