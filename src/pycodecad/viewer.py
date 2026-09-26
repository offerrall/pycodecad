"""The 3D view as an ImGui component: a camera of its own, the view cube, Fit and the display toggles
(experimental in 1.0, see docs/embedding.md)."""
from __future__ import annotations

from collections.abc import Sequence

from . import camera as cam, ui, window
from .cad import Shown
from .renderer import Display, Renderer, png_bytes


class Viewer:
    """Draws the objects it is given (e.g. `Workspace.shown`) into the current ImGui window, between
    `Window.frame()` calls. Left drag orbits, right/middle (or Shift+left) drag pans, the wheel
    zooms, a double click fits. It fits the first objects it gets, and again after a large change."""

    def __init__(self) -> None:
        self.camera = cam.Camera()
        self.display = Display()
        self.size = (1, 1)  # pixels of the last drawn picture
        self.fit_pending = True
        self.objects: list[Shown] = []  # what the renderer holds
        self.renderer: Renderer | None = None  # created at the first draw, on the window's GL context
        window.components.add(self)

    def draw(self, objects: Sequence[Shown], size: tuple[float, float] | None = None) -> None:
        """Draw the objects at size (ImGui units), by default the available region."""
        if self.renderer is None:
            self.renderer = Renderer(window.active().ctx)
        if len(objects) != len(self.objects) or any(a is not b for a, b in zip(objects, self.objects)):
            before = self.bbox()
            self.objects = list(objects)
            self.renderer.set_meshes([(obj.color, obj.mesh, obj.matrix) for obj in self.objects])
            bbox = self.bbox()
            if bbox and (self.fit_pending or cam.needs_fit(before, bbox)):
                self.fit(bbox)
        ui.view(self, size or ui.region())

    def bbox(self) -> cam.BBox | None:
        return cam.scene_bbox([obj.bbox() for obj in self.objects])

    def fit(self, bbox: cam.BBox | None = None) -> None:
        bbox = bbox or self.bbox()
        if bbox:
            self.camera = cam.fit(self.camera, bbox)
            self.fit_pending = False

    def look_from(self, direction: cam.Vec) -> None:
        """Turn the camera to look from a direction (a view cube click) and fit the view."""
        self.camera = cam.look_from(self.camera, direction)
        self.fit()

    def texture(self, width: int, height: int) -> int:
        """Render at this size (pixels); returns the ImGui texture id (the OpenGL texture name)."""
        assert self.renderer is not None
        self.size = (width, height)
        return self.renderer.draw(self.camera, self.display, width, height).glo

    def picture(self) -> bytes:
        """A PNG of the view as last drawn."""
        assert self.renderer is not None
        self.renderer.draw(self.camera, self.display, *self.size)
        return png_bytes(self.renderer.read_image())

    def close(self) -> None:
        """Free the GL resources (Window.close() does it for every open Viewer)."""
        window.components.discard(self)
        if self.renderer is not None:
            self.renderer.release()
            self.renderer = None
