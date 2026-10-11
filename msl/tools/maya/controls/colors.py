# tools/maya/controls/colors.py
"""Colors of controls as data — no Qt, no Maya. These are the SCENE's colors (what a control is
drawn in), the user's data, not the window's theme.

Maya's 32 index colors (`INDEX_COLORS`: what a fresh Maya shows; a running Maya is asked for its
own — the user may have edited its palette), the rig's side colors, and the Outliner's gamma: the
viewport is color managed, the Outliner shows a color's raw values, so the same numbers look darker
there — `to_outliner()` lifts them (gamma 2.2) so both read alike."""

# index -> (r, g, b) 0..1; index 0 = "none" (the default color)
INDEX_COLORS = (
    (0.47, 0.47, 0.47), (0.0, 0.0, 0.0), (0.25, 0.25, 0.25), (0.6, 0.6, 0.6),
    (0.608, 0.0, 0.157), (0.0, 0.016, 0.376), (0.0, 0.0, 1.0), (0.0, 0.275, 0.098),
    (0.149, 0.0, 0.263), (0.784, 0.0, 0.784), (0.541, 0.282, 0.2), (0.247, 0.137, 0.122),
    (0.6, 0.149, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.255, 0.6),
    (1.0, 1.0, 1.0), (1.0, 1.0, 0.0), (0.392, 0.863, 1.0), (0.263, 1.0, 0.639),
    (1.0, 0.69, 0.69), (0.894, 0.675, 0.475), (1.0, 1.0, 0.388), (0.0, 0.6, 0.329),
    (0.631, 0.416, 0.188), (0.62, 0.631, 0.188), (0.408, 0.631, 0.188), (0.188, 0.631, 0.365),
    (0.188, 0.631, 0.631), (0.188, 0.404, 0.631), (0.435, 0.188, 0.631), (0.631, 0.188, 0.416),
)
# the rig's usual side colors: left blue, right red, middle yellow (by the Rename tool's sides)
SIDE_DEFAULTS = {"left": (0.15, 0.45, 1.0), "right": (1.0, 0.15, 0.15), "center": (1.0, 0.85, 0.05)}
# what every part of the tool reads (Create, mirror, "by side", the previews). ONE dict, changed in
# place by `set_side_colors` — so the user's own side colors reach all of them at once
SIDE_COLORS = dict(SIDE_DEFAULTS)


def set_side_colors(texts: "dict | None") -> None:
    """The user's side colors ({"left" / "right" / "center": "#rrggbb"}; a missing or broken one =
    the default) put into SIDE_COLORS, in place."""
    for side, default in SIDE_DEFAULTS.items():
        rgb = None
        try:
            rgb = from_hex(str((texts or {}).get(side, "")))
        except (ValueError, TypeError, AttributeError):
            rgb = None
        SIDE_COLORS[side] = tuple(rgb) if rgb else default
GHOST_ZERO = (0.71, 0.55, 1.0)       # the ghost's frames that stand for zero groups / the matrix
GHOST_DRIVE = (1.0, 0.49, 0.71)      # the ghost's mark for "this control will drive its object"
GAMMA = 2.2


def to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(value * 255))):02x}" for value in rgb[:3])


def from_hex(text: str) -> tuple:
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"not a color: {text!r}")
    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


SHADE_STEP = 0.15           # one click of Lighter / Darker


def shaded(rgb, lighter: bool, step: float = SHADE_STEP) -> tuple:
    """The same hue a step lighter or darker. Darker lowers the value; lighter raises it and — once
    the value is full — lets the saturation go, so a full red still gets lighter (towards pink)."""
    import colorsys
    hue, saturation, value = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, float(channel))) for channel in rgb[:3]])
    if lighter:
        room = 1.0 - value
        value = min(1.0, value + step)
        if room < step:
            saturation = max(0.0, saturation - (step - room))
    else:
        value = max(0.05, value - step)
    return tuple(round(channel, 4) for channel in colorsys.hsv_to_rgb(hue, saturation, value))


def to_outliner(rgb) -> tuple:
    """The values to give the Outliner so it shows what the (color managed) viewport shows."""
    return tuple(round(max(0.0, min(1.0, value)) ** (1.0 / GAMMA), 4) for value in rgb)


def from_outliner(rgb) -> tuple:
    """The viewport color an Outliner color stands for (the other way)."""
    return tuple(round(max(0.0, min(1.0, value)) ** GAMMA, 4) for value in rgb)


def same(a, b, tolerance: float = 1e-3) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))
