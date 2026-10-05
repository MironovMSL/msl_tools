# -*- coding: utf-8 -*-
# tools/maya/batch_runner.py
"""Runs INSIDE Maya for the hub's Batch tool: reads a scene (probe) or renders it frame by frame.

SELF-CONTAINED on purpose (the standard library and maya only; Python-2.7-valid and plain ASCII:
a scene from before Maya 2022 may be read by a Maya 2020): it is started by
path, in a mayapy without a window (`mayapy batch_runner.py <task.json>`) or in a windowed Maya
(`maya.exe -command` with MSL_BATCH_TASK=<task.json>) - no msl_tools on the path is assumed.

The task file (written by core/batch/commands.py) says what to do:
    {"mode": "probe" | "render", "scene": ..., "report": <probe: json path>,
     "progress": <a JSON-lines file the hub reads>, "camera": ..., "frames": [1, 2, ...],
     "width": 0, "height": 0, "folder": ..., "prefix": ..., "renderer": "arnold",
     "skip_existing": true, "window": false}

Every step appends one JSON object to the progress file (and prints it with "@@MSL " in front):
    started, scene_open, frame_start {frame}, frame_done {frame, file, seconds}, frame_skipped,
    frame_failed {frame, error}, finished {rendered, skipped, failed}, failed {error}.

The scene is NEVER saved. What a render changes (the camera that renders, where the frames go,
"render an animation") is changed in memory only.

Arnold and the licence (measured with Maya 2024 + MtoA 5.3, 2026-10-05): a render WITHOUT a window
(`arnoldRender -batch`) needs a batch entitlement - without one every frame carries "arnold"
watermarks. The same frame rendered in a WINDOWED Maya (interactive `arnoldRender` + the Render
View's writeImage) uses the interactive licence and is clean. Hence `"window": true`.
"""
import json
import os
import sys
import time
import traceback

STARTED = time.time()
LIGHT_TYPES = ("light", "aiSkyDomeLight", "aiAreaLight", "aiMeshLight", "aiPhotometricLight",
               "RedshiftPhysicalLight", "RedshiftDomeLight", "RedshiftIESLight", "RedshiftPortalLight",
               "RedshiftSunLight", "RedshiftPhysicalSun")
RENDERER_PLUGINS = {"arnold": "mtoa", "redshift": "redshift4maya"}


class Runner(object):
    def __init__(self, task_path):
        with open(task_path, "r") as handle:
            self.task = json.load(handle)
        self.progress_path = self.task.get("progress", "")

    # --- reporting ----------------------------------------------------------------------------

    def say(self, event, **data):
        data["event"] = event
        data["t"] = round(time.time() - STARTED, 2)
        line = json.dumps(data)
        if self.progress_path:
            try:
                with open(self.progress_path, "a") as handle:
                    handle.write(line + "\n")
            except (IOError, OSError):
                pass
        try:
            sys.__stdout__.write("@@MSL " + line + "\n")
            sys.__stdout__.flush()
        except Exception:
            pass

    # --- the scene ----------------------------------------------------------------------------

    def open_scene(self):
        from maya import cmds
        for plugin in ("mtoa",):
            try:
                cmds.loadPlugin(plugin, quiet=True)
            except Exception:
                pass
        renderer = self.task.get("renderer", "")
        if renderer in RENDERER_PLUGINS:
            try:
                cmds.loadPlugin(RENDERER_PLUGINS[renderer], quiet=True)
            except Exception:
                pass
        warnings = []
        try:
            cmds.file(self.task["scene"], open=True, force=True, ignoreVersion=True, prompt=False)
        except RuntimeError as error:  # missing plug-ins etc.: Maya raises, but the scene IS open
            warnings.append(str(error).strip()[:500])
        self.say("scene_open", warnings=warnings)
        return warnings

    # --- probe --------------------------------------------------------------------------------

    def probe(self):
        from maya import cmds
        report = {"warnings": self.open_scene()}
        report["maya"] = cmds.about(version=True)
        report["renderer"] = cmds.getAttr("defaultRenderGlobals.currentRenderer")
        try:
            report["renderers"] = cmds.renderer(query=True, namesOfAvailableRenderers=True) or []
        except Exception:
            report["renderers"] = []
        report["unknown_plugins"] = cmds.unknownPlugin(query=True, list=True) or []
        cameras = []
        for shape in cmds.ls(type="camera", long=True) or []:
            transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
            cameras.append({"name": transform.split("|")[-1], "renderable": bool(cmds.getAttr(shape + ".renderable")),
                            "startup": bool(cmds.camera(transform, query=True, startupCamera=True))})
        report["cameras"] = cameras
        report["resolution"] = [cmds.getAttr("defaultResolution.width"), cmds.getAttr("defaultResolution.height")]
        report["playback"] = [cmds.playbackOptions(query=True, minTime=True),
                              cmds.playbackOptions(query=True, maxTime=True)]
        report["render_range"] = [cmds.getAttr("defaultRenderGlobals.startFrame"),
                                  cmds.getAttr("defaultRenderGlobals.endFrame"),
                                  bool(cmds.getAttr("defaultRenderGlobals.animation"))]
        report["time_unit"] = cmds.currentUnit(query=True, time=True)
        lights = []
        for light_type in LIGHT_TYPES:
            try:
                lights += cmds.ls(type=light_type) or []
            except Exception:
                continue
        report["lights"] = sorted(set(lights))
        if cmds.objExists("defaultArnoldRenderOptions"):
            report["arnold_aa"] = cmds.getAttr("defaultArnoldRenderOptions.AASamples")
        report["has_redshift_nodes"] = bool(cmds.ls(type="unknown")) and "redshift4maya" in report["unknown_plugins"]
        missing = []
        textures = 0
        for node_type, attribute in (("file", "fileTextureName"), ("aiImage", "filename")):
            try:
                nodes = cmds.ls(type=node_type) or []
            except Exception:
                continue
            for node in nodes:
                path = cmds.getAttr(node + "." + attribute) or ""
                if not path:
                    continue
                textures += 1
                if not _texture_exists(path):
                    missing.append(path)
        report["textures"] = textures
        report["missing_textures"] = sorted(set(missing))
        caches = []
        for node in cmds.ls(type="AlembicNode") or []:
            path = cmds.getAttr(node + ".abc_File") or ""
            caches.append([path, bool(path) and os.path.isfile(path)])
        report["caches"] = caches
        references = []
        for path in cmds.file(query=True, reference=True) or []:
            clean = path.split("{")[0]
            references.append([clean, os.path.isfile(clean)])
        report["references"] = references
        try:
            import maya.app.renderSetup.model.renderSetup as render_setup
            report["render_layers"] = [layer.name() for layer in render_setup.instance().getRenderLayers()]
        except Exception:
            report["render_layers"] = []
        with open(self.task["report"], "w") as handle:
            json.dump(report, handle, indent=1)
        self.say("finished", probe=True)

    # --- render -------------------------------------------------------------------------------

    def render(self):
        from maya import cmds
        task = self.task
        self.open_scene()
        renderer = task.get("renderer", "arnold")
        if renderer != "arnold":
            raise RuntimeError("This runner renders with Arnold only; %s goes through Render.exe." % renderer)
        camera = task["camera"]
        shapes = cmds.listRelatives(camera, shapes=True, fullPath=True) if cmds.objExists(camera) else None
        if not shapes:
            raise RuntimeError("The camera %s isn't in the scene." % camera)
        for shape in cmds.ls(type="camera") or []:
            cmds.setAttr(shape + ".renderable", False)
        cmds.setAttr(shapes[0] + ".renderable", True)
        width = int(task.get("width") or cmds.getAttr("defaultResolution.width"))
        height = int(task.get("height") or cmds.getAttr("defaultResolution.height"))
        folder = task["folder"].replace("\\", "/")
        prefix = task["prefix"]
        if not os.path.isdir(folder):
            os.makedirs(folder)
        cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold", type="string")
        try:  # a windowed Maya makes Arnold's option nodes only when they are first needed
            import mtoa.core
            mtoa.core.createOptions()
        except Exception:
            pass
        if cmds.objExists("defaultArnoldDriver"):
            cmds.setAttr("defaultArnoldDriver.ai_translator", "png", type="string")
        cmds.setAttr("defaultRenderGlobals.imageFilePrefix", prefix, type="string")
        cmds.setAttr("defaultRenderGlobals.animation", True)
        cmds.setAttr("defaultRenderGlobals.putFrameBeforeExt", True)
        cmds.setAttr("defaultRenderGlobals.extensionPadding", 4)
        cmds.setAttr("defaultRenderGlobals.imageFormat", 32)  # png: what the Render View writes
        cmds.setAttr("defaultResolution.width", width)
        cmds.setAttr("defaultResolution.height", height)
        cmds.workspace(fileRule=["images", folder])
        window = bool(task.get("window"))
        if not window and cmds.objExists("defaultArnoldRenderOptions"):
            try:  # "Info": Arnold says how far each frame is ("60% done") - the hub shows the last line
                cmds.setAttr("defaultArnoldRenderOptions.log_verbosity", 2)
            except Exception:
                pass
        rendered = skipped = failed = 0
        frames = [int(frame) for frame in task["frames"]]
        for index, frame in enumerate(frames):
            target = "%s/%s.%04d.png" % (folder, prefix, frame)
            if task.get("skip_existing", True) and os.path.isfile(target) and os.path.getsize(target) > 0:
                skipped += 1
                self.say("frame_skipped", frame=frame, index=index, total=len(frames), file=target)
                continue
            self.say("frame_start", frame=frame, index=index, total=len(frames))
            begun = time.time()
            try:
                if window:  # interactive render into the Render View, then saved from there
                    cmds.currentTime(frame)
                    cmds.arnoldRender(width=width, height=height, camera=shapes[0])
                    cmds.renderWindowEditor("renderView", edit=True, writeImage=target)
                else:
                    cmds.arnoldRender(batch=True, seq=str(frame), camera=shapes[0])
                if not os.path.isfile(target):
                    raise RuntimeError("Arnold wrote no file for frame %d" % frame)
            except Exception as error:
                failed += 1
                self.say("frame_failed", frame=frame, index=index, total=len(frames), error=str(error)[:400])
                continue
            rendered += 1
            self.say("frame_done", frame=frame, index=index, total=len(frames), file=target,
                     seconds=round(time.time() - begun, 2))
        self.say("finished", rendered=rendered, skipped=skipped, failed=failed)

    def run(self):
        self.say("started", mode=self.task.get("mode"), window=bool(self.task.get("window")))
        try:
            if self.task.get("mode") == "probe":
                self.probe()
            else:
                self.render()
        except Exception as error:
            self.say("failed", error=str(error)[:600], trace=traceback.format_exc()[-2000:])


def _texture_exists(path):
    """A texture file - or, for tiles (<UDIM>, .1001.), at least one tile of it."""
    if os.path.isfile(path):
        return True
    folder, name = os.path.split(path)
    for token in ("<UDIM>", "<udim>", "<UVTILE>", "1001"):
        if token in name and os.path.isdir(folder):
            head, tail = name.split(token, 1)
            return any(entry.startswith(head) and entry.endswith(tail) for entry in os.listdir(folder))
    return False


def _minimize_maya():
    """A windowed Maya started for a render keeps out of the way."""
    for module in ("PySide6", "PySide2"):
        try:
            widgets = __import__(module + ".QtWidgets", fromlist=["QtWidgets"])
        except ImportError:
            continue
        for widget in widgets.QApplication.topLevelWidgets():
            if widget.objectName() == "MayaWindow":
                widget.showMinimized()
        return


def main_standalone(task_path):
    import maya.standalone
    maya.standalone.initialize(name="python")
    Runner(task_path).run()
    os._exit(0)  # standalone's own shutdown is slow and noisy; everything is written


def main_windowed():
    """In a windowed Maya: started from -command, runs once Maya is idle, then quits it."""
    from maya import cmds

    def go():
        try:
            _minimize_maya()
        except Exception:
            pass
        try:
            Runner(os.environ["MSL_BATCH_TASK"]).run()
        finally:
            cmds.evalDeferred("import maya.cmds as c; c.quit(force=True)", lowestPriority=True)

    cmds.evalDeferred(go, lowestPriority=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".json"):
        main_standalone(sys.argv[1])          # mayapy batch_runner.py <task.json>
    elif os.environ.get("MSL_BATCH_TASK"):
        main_windowed()                       # exec()'d by a windowed Maya's -command
