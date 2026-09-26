"""pycodecad's parts as Dear ImGui components for your own app (experimental in 1.0: the names may
change in a minor version). See docs/embedding.md.

    window = create_window("My app")
    part = Workspace("part.py")      # code + parameters + 3D view, like the pycodecad window
    viewer = Viewer()                # only a 3D view
    while window.frame(keep_open=part.dirty()):
        imgui.begin("Part"); part.draw(); part.close_prompt(window); imgui.end()
        imgui.begin("Preview"); viewer.draw(part.shown); imgui.end()
    window.close()
"""
from .viewer import Viewer
from .window import Window, create_window
from .workspace import Workspace

__all__ = ["Viewer", "Window", "Workspace", "create_window"]
