# tools/maya/labels/__init__.py
"""Labels: attribute values shown live in Maya's viewport — a tool of ours inside Maya 2025+.

    layout.py   what a set of labels IS: a layout of columns of lines, as plain data that goes to
                and from JSON; namespaces, mirroring, checks (no Qt, no Maya)
    scene.py    the Maya side: a layout built into the scene as mslLabels nodes (one undo step),
                read back from the scene, removed

The nodes are drawn by the plug-in maya_module/plug-ins/msl_labels.py.
"""
