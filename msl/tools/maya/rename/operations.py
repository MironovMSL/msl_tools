# tools/maya/rename/operations.py
"""What a click of the rename tool would do, as a value: new names for a list of nodes. No Qt, no
Maya — the panel builds them, shows them in the list while a button is hovered, runs them."""


class Operation:
    """New names for nodes.

    `names(nodes) -> list[str]` (may raise ValueError: a broken regular expression);
    `drop_namespace`: the objects leave their namespace too; `nodes()`: the objects it works on
    (None = the panel's own: the selection or the held list)."""

    def __init__(self, label: str, names, drop_namespace: bool = False, nodes=None):
        self.label = label
        self.names = names
        self.drop_namespace = drop_namespace
        self.nodes = nodes


def each(function):
    """An Operation's `names` from a function of one node."""
    return lambda nodes: [function(node) for node in nodes]
