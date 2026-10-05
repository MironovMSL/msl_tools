# MSL Tools

A desktop hub and a set of Maya tools for an animation team, by msl.Mironov.

One shortcut opens **MSL Tools**: a window with a sidebar of tools.

- **Maya Gate** — starts any installed Maya in a named environment (Default, Stable, Dev, ...),
  each with its own variables, its own `userSetup` script and its own set of plug-ins skipped at
  startup ("Boost start"). Every Maya started from here stays connected to the hub: the
  *Sessions* tab lists them with their scene, their Script Editor warnings and errors, and lets
  you close, restart or recover one after a crash.
- **Media** — video and image sequences without knowing ffmpeg: sequence to video, make
  smaller, trim, loop, burn-ins, sound, GIF, frames, contact sheet, compare, join and more.
- **Batch** — Maya scenes rendered one after another without opening Maya: drop scenes in, each
  is read and checked first (renderer, lights, camera, missing caches and textures), then
  rendered with Arnold or the viewport renderer, frame by frame, and turned into a video.
- **Playblast** (inside Maya 2025+, *MSL* menu) — playblasts through our own ffmpeg chain, with a
  shot mask drawn in the viewport, versions, several cameras at once and presets.

The hub updates itself: the version at the bottom of the sidebar opens *What's new*, with
**Update now** for a newer release and **Install this version** to go back.

## Install

Requirements: Windows, Python **3.10 – 3.13** (from [python.org](https://www.python.org/downloads/)).
The hub's Qt (PySide6 6.8) has no build for Python 3.14 yet — install 3.13 next to it if needed.

1. Download the latest release (*Source code (zip)*) from
   [Releases](https://github.com/MironovMSL/msl_tools/releases) and unpack it.
2. Double-click `setup_express_launcher.bat`. The first run prepares the hub's own Python
   environment in `%LOCALAPPDATA%\MSL\runtime` (about 100 MB of downloads).
3. In the setup window pick a folder, keep *Create a desktop shortcut*, click **Install**, then
   **Launch MSL Tools**.

Nothing is installed into Maya: Maya Gate passes the tools to the Maya it starts.
Settings and logs stay in `configs/` and `logs/` next to the installed code; an update never
touches them.

Media needs ffmpeg: the tool offers to download a tested build (about 100 MB, once), or you
point it at a copy you already have.

## Develop

The repository folder is the Python package `msl_tools`, so its **parent** folder goes on the
path. Run the hub from a checkout:

```bat
cd <parent of msl_tools>
python -m msl_tools.msl.run_hub
```

In a checkout the hub doesn't update itself, and theme files reload as you save them.

Tests (standard `unittest`, nothing to install; Qt tests skip without PySide6):

```bat
cd msl_tools
python -m unittest discover -s tests -t .
```

`CLAUDE.md` is the detailed map of the code: architecture, conventions, and why things are the
way they are.

Layout: `msl/core/` — no Qt; `msl/ui/` — reusable Qt widgets (atoms → compositions → windows);
`msl/tools/desktop/` — the hub's tools; `msl/tools/maya/` — what runs inside Maya;
`msl/maya_module/` — the Maya module (plug-ins).

## Release

1. Raise `__version_tuple__` in `msl/__init__.py`, commit, push to `main`.
2. Publish a GitHub release tagged `v<version>`, its notes as `### New` / `### Improved` /
   `### Fixed` lists — *What's new* in the hub shows them.

## License

MIT — see [LICENSE](LICENSE).
