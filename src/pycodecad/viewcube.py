"""The view cube in the corner of the 3D view: where its faces land on screen for a camera, and which
view a click on it asks for. Pure geometry; ui.py draws it with ImGui.

The cube spans -1..1 on each axis, turned like the scene. Each face is split in 3 x 3 cells: the
centre looks from that face, a side cell from that edge and a corner cell from that corner (the
corner at +X -Y +Z is the iso view). A cell's direction is where the camera goes, e.g. (0, -1, 1).
"""
from __future__ import annotations

from itertools import product
from typing import Annotated, Literal

from pytypehint import Max, Min, immutable

from . import camera as cam

Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]
Step = Annotated[int, Min(-1), Max(1)]
Direction = tuple[Step, Step, Step]
Label = Literal["RIGHT", "LEFT", "FRONT", "BACK", "TOP", "BOTTOM"]

FACES: tuple[tuple[Direction, Label], ...] = (
    ((1, 0, 0), "RIGHT"), ((-1, 0, 0), "LEFT"), ((0, -1, 0), "FRONT"), ((0, 1, 0), "BACK"),
    ((0, 0, 1), "TOP"), ((0, 0, -1), "BOTTOM"))
NORMALS = {label: normal for normal, label in FACES}
EDGE = 0.62  # the centre cell spans -EDGE..EDGE of a face; beyond are the edge and corner cells
BOUNDS = ((-1.0, -EDGE, -1), (-EDGE, EDGE, 0), (EDGE, 1.0, 1))  # (from, to, direction) along a face axis


def _cell_directions(normal: Direction) -> frozenset[Direction]:
    """The 9 directions of a face's cells: its normal, plus -1, 0 or 1 along each other axis."""
    return frozenset((normal[0] or x, normal[1] or y, normal[2] or z) for x, y, z in product((-1, 0, 1), repeat=3))


CELL_DIRECTIONS = {label: _cell_directions(normal) for normal, label in FACES}


@immutable
class Face:
    label: Label
    normal: Direction  # the label's own, a unit axis direction
    facing: float  # above 0 (seen edge-on) .. 1 (seen straight on)
    light: Annotated[float, Min(0.0), Max(1.0)]  # lit from the upper left of the screen, so neighbouring faces differ
    quad: Quad  # on screen
    center: Point
    cells: tuple[tuple[Direction, Quad], ...]  # (direction, quad on screen): the face's 9 cells

    def __post_init__(self) -> None:
        if self.label not in NORMALS:
            raise ValueError(f"unknown face {self.label!r}")
        if self.normal != NORMALS[self.label]:
            raise ValueError(f"face {self.label}: normal {self.normal} is not {NORMALS[self.label]}")
        if not 0.0 < self.facing <= 1.0:
            raise ValueError(f"face {self.label}: facing {self.facing} not in (0, 1]")
        directions = [direction for direction, _ in self.cells]
        if len(directions) != 9 or set(directions) != CELL_DIRECTIONS[self.label]:
            raise ValueError(f"face {self.label}: cells {directions} are not its 9 directions")


def faces(camera: cam.Camera, center: Point, radius: float) -> list[Face]:
    """The faces the camera sees, for a cube of half-size radius (pixels) drawn around center."""
    right, up, back = cam.basis(camera)
    lamp = [-0.35 * r + 0.75 * u + 0.56 * b for r, u, b in zip(right, up, back)]  # about unit length

    def screen(point) -> Point:
        return (center[0] + sum(p * r for p, r in zip(point, right)) * radius,
                center[1] - sum(p * u for p, u in zip(point, up)) * radius)

    result = []
    for normal, label in FACES:
        facing = min(1.0, sum(n * b for n, b in zip(normal, back)))
        if facing <= 1e-6:
            continue
        axis = next(i for i in range(3) if normal[i])
        first, second = [i for i in range(3) if i != axis]

        def at(u: float, v: float):
            point = [0.0, 0.0, 0.0]
            point[axis], point[first], point[second] = normal[axis], u, v
            return screen(point)

        cells = []
        for u0, u1, du in BOUNDS:
            for v0, v1, dv in BOUNDS:
                direction = [0, 0, 0]
                direction[axis], direction[first], direction[second] = normal[axis], du, dv
                cells.append((tuple(direction), (at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1))))
        light = max(0.0, min(1.0, sum(n * l for n, l in zip(normal, lamp))))
        result.append(Face(label=label, normal=normal, facing=facing, light=light,
                           quad=(at(-1, -1), at(1, -1), at(1, 1), at(-1, 1)), center=at(0, 0), cells=tuple(cells)))
    return result


def inside(point: Point, quad) -> bool:
    """Whether point is in a convex quad (either winding), borders included."""
    signs = set()
    for (x0, y0), (x1, y1) in zip(quad, quad[1:] + quad[:1]):
        cross = (x1 - x0) * (point[1] - y0) - (y1 - y0) * (point[0] - x0)
        if abs(cross) > 1e-9:
            signs.add(cross > 0)
    return len(signs) <= 1


def hit(visible: list[Face], point: Point) -> Direction | None:
    """The direction of the cell under point (visible faces never overlap), or None."""
    for face in visible:
        for direction, quad in face.cells:
            if inside(point, quad):
                return direction
    return None


def name(direction: Direction) -> str:
    """'Front', 'Top front', 'Top front right (iso)'..."""
    x, y, z = direction
    words = [word for value, word in ((z, "top" if z > 0 else "bottom"), (y, "back" if y > 0 else "front"),
                                      (x, "right" if x > 0 else "left")) if value]
    text = " ".join(words).capitalize()
    return text + " (iso)" if direction == (1, -1, 1) else text
