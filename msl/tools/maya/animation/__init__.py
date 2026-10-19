# tools/maya/animation/__init__.py
"""Animation: the animator's tools inside Maya 2025+ — built in phases (the plan: CLAUDE.md).

    curves.py   what the sliders do to keys, as arithmetic: the modes, the slider's feel (no Qt, no Maya)
    scene.py    the Maya side: what a slider acts on (Graph Editor keys, the timeline's range, the
                current frame), a drag that changes the curves live and ends as ONE undo step
    world.py    the pose sliders in world space
    keys.py     keys and timing as arithmetic on key times: nudge, inbetweens, bake, snap, key times (no Qt, no Maya)
    keys_scene.py  those commands in the scene, one undo step each (what they act on: picked keys / range / frame)
    keys_row.py the KEYS row under the sliders (nudge, and six groups that show the action used last)
    panel.py    AnimationPanel (the POSE and CURVE sliders, their modes, the frames to blend to, the KEYS row),
    window.py   AnimationWindow
    animation.qss

Nothing is imported here until the tool is opened: the menu refers to `launcher_entry_point`
by name only.
"""


def launcher_entry_point():
    """Opens the Animation window (the MSL menu's entry). Returns the window; its `panel` is the tool."""
    from msl_tools.msl.tools.maya.animation.window import AnimationWindow
    return AnimationWindow.open()


def nudge(mode: str, weight: float) -> None:
    """One slider step without the window - for hotkeys: `mode` (curves.MODES' key) by `weight`, on
    what the sliders would act on now; one undo step, said in the viewport."""
    from msl_tools.msl.tools.maya.animation import scene
    scene.apply_once(mode, weight, say=True)


def key_action(call: str, *args) -> str:
    """One KEYS-row action without the window - for hotkeys: keys_scene's `call` with `args` ("N" / "-N" = the
    window's frames number, as it was left), on what it acts on now; one undo step, said in the viewport."""
    from msl_tools.msl.core.resources import Resources
    from msl_tools.msl.tools.maya.animation import keys_scene
    settings = Resources().configsMayaMng.get_config("animation", defaults={"settings": {}}).data.get("settings") or {}
    frames = float(settings.get("frames") or 1.0)
    values = [frames if a == "N" else -frames if a == "-N" else a for a in args]
    return getattr(keys_scene, call)(*values, say=True)
