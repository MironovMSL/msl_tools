"""Data contract between the hub window and individual tools."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    import msl_tools.msl.ui.qt_bindings as qt


@dataclass(frozen=True)
class ToolDescriptor:
    """Describes a single tool entry the hub can display.

    The hub only ever handles descriptors as data — it has no knowledge of
    what a tool actually does, which keeps the hub itself free of any
    tool-specific logic.

    Attributes:
        id: Unique, stable identifier for the tool (used for lookups and
            logging, not shown in the UI).
        title: Label shown on the tool's entry in the hub sidebar.
        widget_factory: Zero-argument callable that creates the tool's page
            widget on demand. The hub calls this lazily, on first
            selection, so a tool the user never opens is never
            constructed.
    """

    id: str
    title: str
    widget_factory: Callable[[], "qt.QtWidgets.QWidget"]