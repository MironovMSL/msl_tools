"""Central registry of tools shown in the desktop hub.

Adding a new tool means adding one import and one line here — the hub
itself never needs to change.
"""
from msl_tools.msl.tools.desktop import stub_a, stub_b, maya_gate

TOOLS = [
    maya_gate.TOOL_DESCRIPTOR,
    stub_a.TOOL_DESCRIPTOR,
    stub_b.TOOL_DESCRIPTOR,
]