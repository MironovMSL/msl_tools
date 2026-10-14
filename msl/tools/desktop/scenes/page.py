# tools/desktop/scenes/page.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.batch.page import BatchPage
from msl_tools.msl.tools.desktop.scene_paths.page import ScenePathsPage
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.tabs.base_tab_bar import BaseTabWidget

StylesheetBuilder.register_template(Path(__file__).with_name("scenes.qss"))


class ScenesPage(qt.QtWidgets.QWidget):
    """Scenes — many Maya scenes at once, Maya closed. One heading, one tab per kind of work:

    - Render: the render queue (BatchPage — core/batch, a mayapy / Render.exe per scene);
    - Paths: absolute paths swapped for Maya Gate's variables (ScenePathsPage — core/scene_paths).

    Each tab keeps its OWN list of scenes, on purpose: Render reads every scene added to it in
    Maya (~10 s each), so a folder of 300 scenes dropped to fix their paths must not become 300
    Mayas. The tabs hand scenes to each other instead: a render job's menu "Check its paths"
    (paths_requested), a Paths row's "Render it" (render_requested). The open tab is kept in
    configsDesktopHubMng "scenes" (`settings.tab`). The tabs keep their own configs and queue
    ("batch", "scene_paths") from when they were tools of their own.
    """

    TOOL_NAME = "scenes"
    RENDER, PATHS = "render", "paths"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = Resources().configsDesktopHubMng.get_config(self.TOOL_NAME, defaults={"settings": {}})
        self._settings = self._config["settings"]
        icons = UiResources().iconManager
        title_icon = TintedIcon(icons.get_icon("scenes", sub_folder="tools"), 16)
        title_icon.setObjectName("scenesTitleIcon")
        title = qt.QtWidgets.QLabel("SCENES")
        title.setObjectName("scenesTitle")
        subtitle = qt.QtWidgets.QLabel("Many Maya scenes at once — Maya stays closed")
        subtitle.setObjectName("scenesSubtitle")
        header = qt.QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(title_icon)
        header.addWidget(title)
        header.addWidget(subtitle, 1)

        self.render = BatchPage(embedded=True)
        self.paths = ScenePathsPage(embedded=True)
        self._pages = {self.RENDER: self.render, self.PATHS: self.paths}
        self._tabs = BaseTabWidget()   # sliding accent indicator
        self._tabs.setObjectName("scenesTabs")
        self._tabs.addTab(self.render, "Render")
        self._tabs.addTab(self.paths, "Paths")
        self._tabs.setTabToolTip(0, "Scenes rendered one after another — Arnold, Viewport, Redshift")
        self._tabs.setTabToolTip(1, "Absolute paths in .ma scenes swapped for Maya Gate’s variables ($WG_ANIM/…)")
        saved = str(self._settings.get("tab") or self.RENDER)
        self._tabs.setCurrentWidget(self._pages.get(saved, self.render))

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._tabs, 1)

        self._tabs.currentChanged.connect(self._on_tab)
        self.render.paths_requested.connect(self._to_paths)
        self.render.focus_requested.connect(lambda: self.show_tab(self.RENDER))
        self.paths.render_requested.connect(self._to_render)

    def current_tab(self) -> str:
        return self.PATHS if self._tabs.currentWidget() is self.paths else self.RENDER

    def show_tab(self, key: str) -> None:
        page = self._pages.get(key)
        if page is not None:
            self._tabs.setCurrentWidget(page)

    def open(self, paths) -> None:
        """Scenes handed to the tool from outside (the hub, a test): the tab on screen takes them."""
        self._pages[self.current_tab()].open(paths)

    def _on_tab(self, _index: int) -> None:
        self._settings["tab"] = self.current_tab()

    def _to_paths(self, scenes: list) -> None:
        self.show_tab(self.PATHS)
        self.paths.add(scenes)

    def _to_render(self, scenes: list) -> None:
        self.show_tab(self.RENDER)
        self.render.add_scenes(scenes)
