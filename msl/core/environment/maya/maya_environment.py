import logging
from enum import Enum

logger = logging.getLogger(__name__)

class MayaEnvironment:
    """Detects the Maya runtime in the current process.
    A pure query layer: no cache, no side effects, never initializes standalone itself."""


    class State(Enum):
        NOT_RUNNING = "not_running"   # maya.cmds is not available at all (plain interpreter/IDE)
        INTERACTIVE = "interactive"   # maya.exe, full GUI
        BATCH       = "batch"         # mayapy / maya -batch / maya.standalone.initialize()

    @classmethod
    def get_state(cls) -> "MayaEnvironment.State":
        try:
            import maya.cmds as cmds
        except ImportError:
            return cls.State.NOT_RUNNING

        try:
            return cls.State.BATCH if cmds.about(batch=True) else cls.State.INTERACTIVE
        except AttributeError:
            # cmds is imported but not fully initialized
            # (mayapy/standalone before maya.standalone.initialize(), or a transitional moment while the GUI loads).
            # Treated as BATCH: in practice the most common real cause of this error.
            return cls.State.BATCH

    @classmethod
    def is_running(cls) -> bool:
        return cls.get_state() != cls.State.NOT_RUNNING

    @classmethod
    def is_interactive(cls) -> bool:
        return cls.get_state() == cls.State.INTERACTIVE

    @classmethod
    def is_batch(cls) -> bool:
        return cls.get_state() == cls.State.BATCH

    @classmethod
    def get_version(cls) -> str | None:
        try:
            import maya.cmds as cmds
            return cmds.about(version=True)
        except Exception as e:
            logger.warning(f'Unable to retrieve Maya version. Issue: "{e}".')
            return None



if __name__ == '__main__':
    print(MayaEnvironment.get_state())