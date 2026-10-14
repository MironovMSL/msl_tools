# core/link/variables.py
"""The environment variables Maya Gate hands to a Maya it launches — one list
for every side that reads or writes them: Maya Gate (page.py, boost.py), the
hub's link server, and inside Maya the link (hub_link.py) and the launch
report. A name changed in one place only would silently break the link or the
startup measurement.

No imports, nothing newer than Python 2.7: anything may import this. The boost
loader (boost.py) is generated code that runs alone inside Maya and spells
the names out itself — tests/core/test_maya_gate.py checks it uses these.
"""

ENVIRONMENT = "MSL_GATE_ENVIRONMENT"          # the Maya Gate environment of this launch
VARIABLES = "MSL_GATE_VARIABLES"              # os.pathsep-joined names of the variables this launch set
CONSOLE = "MSL_GATE_CONSOLE"                  # "1": this Maya may be sent code (Maya Gate sets it at launch)
KEEP_ENGLISH = "MSL_GATE_KEEP_ENGLISH"        # "1": English keyboard while Maya is active (tools/maya/keyboard_keeper.py)
SCENE_FPS = "MSL_GATE_SCENE_FPS"              # "30": new scenes start at this rate (tools/maya/scene_defaults.py)
SCENE_CHECK = "MSL_GATE_SCENE_CHECK"          # "1": say so when an opened scene or a reference is at another rate
SCENE_RANGE = "MSL_GATE_SCENE_RANGE"          # "1 120": playback range of new scenes (core/link/scene_settings.py)
SCENE_UNITS = "MSL_GATE_SCENE_UNITS"          # "cm": linear unit of new scenes
SCENE_UP = "MSL_GATE_SCENE_UP"                # "y" / "z": Maya's up axis
SCENE_SPEED = "MSL_GATE_SCENE_SPEED"          # "every" / "realtime" / "half" / "double": playback speed
SCENE_TANGENTS = "MSL_GATE_SCENE_TANGENTS"    # "auto" / "linear" / "stepped" ...: tangents of new keys
SCENE_AUTO_KEY = "MSL_GATE_SCENE_AUTO_KEY"    # "on" / "off"
SCENE_PATHS_CHECK = "MSL_GATE_SCENE_PATHS_CHECK"   # "1": say so when an opened scene's paths could use a variable

LINK_PORT = "MSL_GATE_LINK_PORT"              # the hub's link server
LINK_TOKEN = "MSL_GATE_LINK_TOKEN"            # its secret: never printed, never sent (core/link/protocol.py)

BOOST_SKIP = "MSL_GATE_BOOST_SKIP"            # os.pathsep-joined plug-ins; its PRESENCE switches the loader on
BOOST_REPORT = "MSL_GATE_BOOST_REPORT"        # where the loader writes what it loaded
BOOST_ENVIRONMENT = "MSL_GATE_BOOST_ENVIRONMENT"

LAUNCH_TIME = "MSL_GATE_LAUNCH_TIME"          # time.time() of the click in Maya Gate
LAUNCH_FILE = "MSL_GATE_LAUNCH_FILE"          # this launch's record; the loader adds the startup time to it
STARTUP_SECONDS = "MSL_GATE_STARTUP_SECONDS"  # set inside Maya once: how long the start took

ALL = (ENVIRONMENT, VARIABLES, CONSOLE, KEEP_ENGLISH, SCENE_FPS, SCENE_CHECK, SCENE_RANGE, SCENE_UNITS, SCENE_UP,
       SCENE_SPEED, SCENE_TANGENTS, SCENE_AUTO_KEY, SCENE_PATHS_CHECK, LINK_PORT, LINK_TOKEN, BOOST_SKIP, BOOST_REPORT, BOOST_ENVIRONMENT,
       LAUNCH_TIME, LAUNCH_FILE, STARTUP_SECONDS)
