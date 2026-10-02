"""Central registry of tools shown in the desktop hub.

Adding a new tool means adding one import and one line here — the hub
itself never needs to change.

The stub tools (placeholders for testing the hub's navigation) are listed
only in a developer's git checkout: an installed copy shows real tools only.
"""
from pathlib import Path

from msl_tools.msl.tools.desktop import maya_gate

TOOLS = [
    maya_gate.TOOL_DESCRIPTOR,
]

if (Path(__file__).resolve().parents[3] / ".git").exists():
    from msl_tools.msl.tools.desktop import stub_a, stub_b

    TOOLS += [stub_a.TOOL_DESCRIPTOR, stub_b.TOOL_DESCRIPTOR]
