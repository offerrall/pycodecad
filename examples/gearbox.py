"""The parts composed into a gearbox: two meshing gears on shafts, on a plate held by brackets.
Each part is built once here; gearbox() only places them, so an animation of it is cheap."""
from build123d import Pos, Rot
from build123d.topology import Shape

from parts import bracket, gear, pitch_radius, plate, shaft

SMALL, LARGE, MODULE = 12, 24, 2.0
BACKLASH = 0.3
DISTANCE = pitch_radius(SMALL, MODULE) + pitch_radius(LARGE, MODULE) + BACKLASH
AXES = [(-DISTANCE / 2, 0.0), (DISTANCE / 2, 0.0)]
PLATE = 5.0

PINION, WHEEL = gear(SMALL, MODULE), gear(LARGE, MODULE)
SHAFT, BRACKET = shaft(6.0, 30.0), bracket(40.0, 4.0)
WIDTH = DISTANCE + 80
BASE = plate(WIDTH, 70, PLATE, AXES)


def gearbox(angle: float = 0.0) -> list[tuple[str, Shape | list[Shape], str]]:
    """(name, parts, color) with the pinion turned by angle degrees (the wheel follows)."""
    (x0, y0), (x1, y1) = AXES
    half_tooth = 180 / LARGE
    return [
        ("plate", BASE, "#9AA3AB"),
        ("shaft", [Pos(x, y, PLATE) * SHAFT for x, y in AXES], "#D0D4D8"),
        ("pinion", Pos(x0, y0, PLATE + 12) * Rot(0, 0, angle) * PINION, "#F4B02A"),
        ("wheel", Pos(x1, y1, PLATE + 12) * Rot(0, 0, half_tooth - angle * SMALL / LARGE) * WHEEL, "#6947AE"),
        ("bracket", [Pos(-WIDTH / 2, 0, 0) * Rot(0, 0, 180) * BRACKET, Pos(WIDTH / 2, 0, 0) * BRACKET], "#48B5A4"),
    ]
