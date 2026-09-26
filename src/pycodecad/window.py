"""A GLFW window with Dear ImGui drawn by pycodecad's backend: the frame loop that Workspaces and Viewers
draw in (experimental in 1.0, see docs/embedding.md). One Window per process."""
from __future__ import annotations

import weakref
from pathlib import Path

import glfw
import moderngl
import numpy as np

from . import ui
from .imgui_backend import ImguiBackend
from .renderer import png_bytes

IDLE, BUSY = 0.25, 0.05  # seconds a frame waits for input (BUSY: while a script runs)

current: Window | None = None  # the window whose frame is being built
components: weakref.WeakSet = weakref.WeakSet()  # open Workspaces and Viewers: Window.close() closes them


def active() -> Window:
    if current is None:
        raise RuntimeError("pycodecad components draw between Window.frame() calls")
    return current


class Window:
    """handle: a GLFW window whose OpenGL 3.3 core context is current. pycodecad installs its ImGui
    backend on it (an ImGui context, fonts, style, the window's input callbacks; close() puts back
    the callbacks it replaced). ctx: the host's moderngl context on it, if it has one (close() never
    releases it); else the Window makes its own. owns: close() also destroys the window and
    terminates GLFW (create_window's windows)."""

    def __init__(self, handle, ctx: moderngl.Context | None = None, owns: bool = False) -> None:
        self.handle, self.owns, self.owns_ctx = handle, owns, ctx is None
        self.ctx = moderngl.create_context() if ctx is None else ctx
        self.gui = ImguiBackend(handle, self.ctx)
        ui.apply_style()
        self.events: list = []  # typed text and key presses of this frame (see ImguiBackend.events)
        self.timeout = 0.0  # how long the next frame() waits for input; the first one does not
        self.close_requested = False  # the user asked to close while frame(keep_open=True)
        self.drawing = False  # between frame() and the next one
        self.picture: str | None = None
        self.title = ""
        self.closed = False

    def frame(self, keep_open: bool = False) -> bool:
        """Show the frame built since the last call, wait for input and begin the next ImGui frame.
        False when the window closes. keep_open (e.g. unsaved changes): a close request only sets
        close_requested, and the frames go on."""
        global current
        if self.drawing:
            self.finish()
        glfw.wait_events_timeout(self.timeout)
        self.timeout = IDLE
        if glfw.window_should_close(self.handle):
            if not keep_open:
                current = None
                return False
            glfw.set_window_should_close(self.handle, False)
            self.close_requested = True
        self.events = self.gui.input_events()
        self.gui.new_frame()
        self.drawing, current = True, self
        return True

    def finish(self) -> None:
        width, height = glfw.get_framebuffer_size(self.handle)
        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(*ui.BACKGROUND[:3])
        self.gui.render()
        self.drawing = False
        if self.picture:
            pixels = self.ctx.screen.read(viewport=(0, 0, width, height), components=3, alignment=1)
            image = np.flipud(np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3))
            Path(self.picture).write_bytes(png_bytes(image))
            self.picture = None
        glfw.swap_buffers(self.handle)

    def screenshot(self, path: str) -> None:
        """Save this frame as a PNG when it is shown (at the next frame())."""
        self.picture = path

    def set_title(self, title: str) -> None:
        if title != self.title:
            self.title = title
            glfw.set_window_title(self.handle, title)

    def request_close(self) -> None:
        """Close as if the user did (frame(keep_open=True) still keeps it open)."""
        glfw.set_window_should_close(self.handle, True)

    def close(self) -> None:
        """Close the open Workspaces and Viewers, then pycodecad's ImGui backend (and the window it owns)."""
        global current
        if self.closed:
            return
        self.closed, current = True, None
        for component in list(components):
            component.close()
        self.gui.shutdown()
        if self.owns_ctx:
            self.ctx.release()
        if self.owns:
            glfw.destroy_window(self.handle)
            glfw.terminate()


def create_window(title: str = "pycodecad", size: tuple[int, int] = (1440, 880), visible: bool = True) -> Window:
    """A new GLFW window with an OpenGL 3.3 context, ready for ImGui. visible False: a hidden window
    (tests, screenshots)."""
    if not glfw.init():
        raise RuntimeError("Could not initialize GLFW")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.VISIBLE, visible)
    handle = glfw.create_window(*size, title, None, None)
    if not handle:
        glfw.terminate()
        raise RuntimeError("Could not create an OpenGL 3.3 window")
    glfw.make_context_current(handle)
    glfw.swap_interval(1 if visible else 0)  # a hidden window never gets vsync frames
    window = Window(handle, owns=True)
    window.title = title
    return window
