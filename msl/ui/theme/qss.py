# ui/theme/qss.py
"""Helpers for widgets that take their colors from the QSS templates
(ui/theme/base.qss, ui/theme/widgets.qss) instead of from a Theme object.

How it works: a custom-painted widget declares each color it paints with
as a Qt property (color_property below). The window's stylesheet sets it:

    GlyphButton { qproperty-glyphColor: var(--text-secondary); }

Qt applies `qproperty-*` whenever it polishes the widget — on first show
and whenever the window's stylesheet changes (i.e. on every theme switch
and hot reload) — so no set_theme() calls have to be passed down.

State that should change colors goes in a dynamic property the QSS can
select on (`[state="error"]`); after changing it, call repolish(), because
Qt only re-matches selectors during polish.
"""
import msl_tools.msl.ui.qt_bindings as qt


def color_property(attribute: str, on_change: str | None = "update"):
    """A QColor Qt property backed by `self.<attribute>`, settable from QSS as
    `qproperty-<name>`. After a change it calls `self.<on_change>()`
    (default: update(), i.e. repaint); pass None for no callback.

    Usage (class body):
        glyphColor = color_property("_glyph_color")
    The widget must set `self._glyph_color` (its default, used until the
    stylesheet is applied — or forever outside a styled window) in __init__.
    """
    def getter(self) -> qt.QtGui.QColor:
        return getattr(self, attribute, qt.QtGui.QColor())

    def setter(self, value) -> None:
        setattr(self, attribute, qt.QtGui.QColor(value))
        if on_change is not None:
            getattr(self, on_change)()

    return qt.QtCore.Property(qt.QtGui.QColor, getter, setter)


def make_rounded_popup(popup: qt.QtWidgets.QWidget) -> qt.QtWidgets.QWidget:
    """Lets a popup window (QMenu, ...) show the QSS `border-radius` for real.

    A popup is its own OS window, and a window is always a rectangle: QSS
    paints the rounded frame, but the pixels outside the corners are still
    opaque window background — the corners stay square. Making the window
    translucent leaves those pixels empty. The native drop shadow is turned
    off too: it's rectangular and would outline the square corners anyway.

    The popup also gets Fusion as its base style: Qt 6.7+'s default
    "windows11" style paints its own shadow into a QMenu's bottom-right
    corner, ignoring the QSS — a dark notch right where the rounded corner
    should be transparent. Our QSS draws everything visible anyway; only
    this popup's base style changes, never the app's (inside Maya, the
    application style is Maya's own).

    Call right after creating the popup (with a parent inside a styled
    window, so it inherits the QSS). Returns `popup` for chaining.
    """
    flags = (popup.windowFlags()
             | qt.QtCore.Qt.WindowType.FramelessWindowHint
             | qt.QtCore.Qt.WindowType.NoDropShadowWindowHint)
    popup.setWindowFlags(flags)
    popup.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    popup.setStyle(_popup_base_style())
    return popup


_POPUP_BASE_STYLE = None


def _popup_base_style():
    """One shared Fusion style for rounded popups. QWidget.setStyle() does
    not take ownership, so the module keeps it alive."""
    global _POPUP_BASE_STYLE
    if _POPUP_BASE_STYLE is None:
        _POPUP_BASE_STYLE = qt.QtWidgets.QStyleFactory.create("Fusion")
    return _POPUP_BASE_STYLE


def repolish(widget: qt.QtWidgets.QWidget) -> None:
    """Re-applies the stylesheet to `widget` after a dynamic property that
    QSS selects on (e.g. `[state="error"]`) changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
