"""The pycodecad window (`pycodecad file.py` or `pycodecad folder/`): one Workspace filling a Window."""
from __future__ import annotations

from slimgui import imgui

from . import __version__
from .window import create_window
from .workspace import Workspace


def open_window(path: str, screenshot: str | None = None, read_only: bool = False, run: bool = True) -> None:
    """Work on a folder until the window closes. path: its main file, or the folder. screenshot: a
    hidden window that saves a PNG of itself after the first run, then closes."""
    workspace = Workspace(path, read_only=read_only, run=run or screenshot is not None)
    window = create_window(workspace.title(), visible=screenshot is None)
    workspace.say(f"pycodecad {__version__}")
    try:
        while window.frame(keep_open=workspace.dirty() and not screenshot):
            window.set_title(workspace.title())
            viewport = imgui.get_main_viewport()
            imgui.set_next_window_pos(viewport.work_pos)
            imgui.set_next_window_size(viewport.work_size)
            imgui.push_style_var(imgui.StyleVar.WINDOW_PADDING, (6.0, 6.0))
            imgui.begin("pycodecad", flags=imgui.WindowFlags.NO_DECORATION | imgui.WindowFlags.NO_MOVE
                        | imgui.WindowFlags.NO_SAVED_SETTINGS | imgui.WindowFlags.NO_BRING_TO_FRONT_ON_FOCUS)
            imgui.pop_style_var()
            workspace.draw()
            workspace.close_prompt(window)
            imgui.end()
            if screenshot and workspace.ran() and not workspace.running():
                window.screenshot(screenshot)
                window.request_close()
    finally:
        window.close()
