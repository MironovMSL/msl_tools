# tools/maya/animation/__init__.py
"""Animation: the animator's tools inside Maya 2025+ — built in phases (the plan: CLAUDE.md).

    curves.py   what the sliders do to keys, as arithmetic: the modes, the slider's feel (no Qt, no Maya)
    scene.py    the Maya side: what a slider acts on (Graph Editor keys, the timeline's range, the
                current frame), a drag that changes the curves live and ends as ONE undo step
    slider.py   BlendSlider: the painted slider (marks, a knob that springs back, the mode on it)
    panel.py    AnimationPanel (the POSE and CURVE sliders, their modes, the frame to blend to),
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
