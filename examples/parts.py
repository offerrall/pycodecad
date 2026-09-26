"""The loose parts: one function per part, no show(). The other scripts compose them."""
from math import cos, pi, sin
from typing import Annotated

from build123d import Align, Box, Cylinder, Polygon, Pos, extrude
from build123d.topology import Shape
from pytypehint import Label, Max, Min, Slider

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def pitch_radius(teeth: int, module: float) -> float:
    return module * teeth / 2


def gear(teeth: Annotated[int, Min(8), Max(60), Slider(), Label("Teeth")] = 20,
         module: Annotated[float, Min(0.5), Max(4.0), Slider(), Label("Module")] = 2.0,
         thickness: Annotated[float, Min(2.0), Max(30.0), Slider(), Label("Thickness")] = 8.0,
         bore: Annotated[float, Min(2.0), Max(20.0), Label("Bore")] = 6.0) -> Shape:
    """Spur gear with straight flanks and a hub, centred on the origin, standing on z=0."""
    root, tip = pitch_radius(teeth, module) - 1.25 * module, pitch_radius(teeth, module) + module
    outline = [(r * cos(a), r * sin(a))
               for i in range(teeth)
               for r, a in ((root, (2 * i - 0.62) * pi / teeth), (tip, (2 * i - 0.3) * pi / teeth),
                            (tip, (2 * i + 0.3) * pi / teeth), (root, (2 * i + 0.62) * pi / teeth))]
    body = extrude(Polygon(*outline, align=None), thickness)
    body += Pos(0, 0, thickness) * Cylinder(bore, thickness / 2, align=BOTTOM)
    return body - Cylinder(bore / 2, thickness * 4)


def shaft(diameter: float = 6.0, length: float = 30.0) -> Shape:
    return Cylinder(diameter / 2, length, align=BOTTOM)


def plate(width: float, depth: float, thickness: float, holes: list[tuple[float, float]]) -> Shape:
    body = Box(width, depth, thickness, align=BOTTOM)
    for x, y in holes:
        body -= Pos(x, y, 0) * Cylinder(3.2, thickness, align=BOTTOM)
    return body


def bracket(length: float = 40.0, thickness: float = 4.0) -> Shape:
    """L bracket with a mounting hole, its corner on the origin."""
    base = Pos(length / 2, 0, thickness / 2) * Box(length, 20, thickness)
    wall = Pos(thickness / 2, 0, 12) * Box(thickness, 20, 24)
    return base + wall - Pos(length * 0.6, 0, thickness / 2) * Cylinder(3, thickness)
