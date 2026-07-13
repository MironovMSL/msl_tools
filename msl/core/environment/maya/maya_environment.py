import logging
from enum import Enum

logger = logging.getLogger(__name__)

class MayaEnvironment:
    """Детекция рантайма Maya в текущем процессе.
    Чистый query-слой: без кэша, без side effects, не инициализирует standalone сам."""


    class State(Enum):
        NOT_RUNNING = "not_running"   # maya.cmds недоступен вовсе (обычный интерпретатор/IDE)
        INTERACTIVE = "interactive"   # maya.exe, полноценный GUI
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
            # cmds импортирован, но не полностью инициализирован
            # (mayapy/standalone до maya.standalone.initialize(), либо переходный момент загрузки GUI).
            # Трактуем как BATCH — это самая частая реальная причина такой ошибки на практике.
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