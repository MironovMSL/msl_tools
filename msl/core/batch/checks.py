# core/batch/checks.py
"""What a scene's probe (tools/maya/batch_runner.py) means for its render — in three tones:
ERROR = the render would fail or come out wrong (no renderer plug-in, no light, an animation cache
missing), WARNING = worth a look (missing textures, very slow settings), OK = checked and fine.

What a render sets for itself (the camera that renders, the frames, "render an animation", the
image format) is never a problem here: the runner changes it in memory, the scene stays as it is.
"""
from __future__ import annotations

from dataclasses import dataclass

from msl_tools.msl.core.batch.frames import FramesError
from msl_tools.msl.core.batch.job import ARNOLD, AUTO, HW2, MODE_WINDOW, REDSHIFT, BatchJob

ERROR, WARNING, OK = "error", "warning", "ok"
SCENE_RENDERERS = {"arnold": ARNOLD, "redshift": REDSHIFT, "mayaHardware2": HW2}
RENDERER_PLUGINS = {ARNOLD: "mtoa", REDSHIFT: "redshift4maya"}
SLOW_AA = 7          # Arnold camera samples above this: every frame takes long
LISTED = 4           # missing files named in a line; the rest are in its detail


@dataclass(frozen=True)
class Issue:
    level: str
    text: str
    detail: str = ""


def choose_renderer(job: BatchJob) -> str:
    """The renderer a job uses: its own choice, else what the scene was set up for."""
    if job.renderer != AUTO:
        return job.renderer
    probe = job.probe
    scene = SCENE_RENDERERS.get(probe.get("renderer", ""))
    if scene:
        return scene
    if "redshift4maya" in (probe.get("unknown_plugins") or []):
        return REDSHIFT  # set up for Redshift, which this Maya doesn't have
    return ARNOLD


def check(job: BatchJob) -> list[Issue]:
    """The job's issues, the worst first. Empty while the scene hasn't been read."""
    probe = job.probe
    if not probe:
        return []
    issues: list[Issue] = []
    renderer = choose_renderer(job)
    available = set(probe.get("renderers") or [])
    plugin = RENDERER_PLUGINS.get(renderer)
    renderer_names = {ARNOLD: "arnold", REDSHIFT: "redshift", HW2: "mayaHardware2"}
    title = {ARNOLD: "Arnold", REDSHIFT: "Redshift", HW2: "Viewport (Hardware 2.0)"}[renderer]
    if renderer_names[renderer] not in available and renderer != HW2:
        issues.append(Issue(ERROR, f"{title} isn’t installed in Maya {probe.get('maya', '')}",
                            f"The plug-in {plugin} wasn’t found."))
    else:
        issues.append(Issue(OK, f"{title} in Maya {probe.get('maya', '')}"))
    unknown = [name for name in probe.get("unknown_plugins") or [] if name != plugin]
    if unknown:
        issues.append(Issue(WARNING, f"Plug-ins the scene asks for aren’t there: {', '.join(unknown[:LISTED])}",
                            "\n".join(unknown)))
    lights = probe.get("lights") or []
    if renderer in (ARNOLD, REDSHIFT) and not lights:
        issues.append(Issue(ERROR, "No lights — the frames will be black"))
    elif lights:
        issues.append(Issue(OK, f"{len(lights)} light{'s' if len(lights) != 1 else ''}"))
    cameras = [camera["name"] for camera in probe.get("cameras") or []]
    camera = job.camera_name()
    if not camera or camera not in cameras:
        issues.append(Issue(ERROR, f"The camera {camera or '(none)'} isn’t in the scene"))
    else:
        renderable = [entry["name"] for entry in probe.get("cameras") or [] if entry.get("renderable")]
        note = "" if camera in renderable else " · made renderable for the render"
        issues.append(Issue(OK, f"Camera {camera}{note}"))
    caches = probe.get("caches") or []
    gone = [path for path, there in caches if not there]
    if gone:
        issues.append(Issue(ERROR, f"{len(gone)} animation cache{'s' if len(gone) != 1 else ''} missing — "
                                   f"what they animate won’t be in the frames", "\n".join(gone)))
    elif caches:
        issues.append(Issue(OK, f"{len(caches)} animation cache{'s' if len(caches) != 1 else ''} found"))
    references = probe.get("references") or []
    lost = [path for path, there in references if not there]
    if lost:
        issues.append(Issue(ERROR, f"{len(lost)} referenced file{'s' if len(lost) != 1 else ''} missing",
                            "\n".join(lost)))
    elif references:
        issues.append(Issue(OK, f"{len(references)} reference{'s' if len(references) != 1 else ''} found"))
    missing = probe.get("missing_textures") or []
    textures = int(probe.get("textures") or 0)
    if missing and renderer != HW2:
        issues.append(Issue(WARNING, f"{len(missing)} of {textures} texture{'s' if textures != 1 else ''} missing",
                            "\n".join(missing)))
    elif textures:
        issues.append(Issue(OK, f"{textures} texture{'s' if textures != 1 else ''} found"))
    aa = probe.get("arnold_aa")
    if renderer == ARNOLD and aa and aa > SLOW_AA:
        issues.append(Issue(WARNING, f"Arnold camera samples are {aa} — every frame will take long",
                            "3–5 is usual for a review."))
    relinked = probe.get("relinked") or []
    if relinked:
        issues.append(Issue(OK, f"{len(relinked)} missing file{'s' if len(relinked) != 1 else ''} found in the "
                                f"search folder — used for the render", "\n".join(new for _old, new in relinked)))
    layers = probe.get("render_layers") or []
    if job.layer and job.layer not in layers:
        issues.append(Issue(ERROR, f"The render layer {job.layer} isn’t in the scene"))
    if job.image_format == "exr" and renderer == ARNOLD and job.mode == MODE_WINDOW:
        issues.append(Issue(ERROR, "EXR frames need “no window” — Maya’s Render View saves 8-bit pictures"))
    try:
        frames = job.frame_list()
    except FramesError as error:
        issues.append(Issue(ERROR, str(error)))
    else:
        if not frames:
            issues.append(Issue(ERROR, "No frames to render"))
    order = {ERROR: 0, WARNING: 1, OK: 2}
    return sorted(issues, key=lambda issue: order[issue.level])


def worst(issues: list[Issue]) -> str:
    """The worst tone among `issues` (OK when there are none)."""
    levels = {issue.level for issue in issues}
    return ERROR if ERROR in levels else WARNING if WARNING in levels else OK
