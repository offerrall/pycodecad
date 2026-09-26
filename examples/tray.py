"""Open tray made to measure: expose() gives the window a control per parameter (units: mm).

Change the values in the window and press Run (Ctrl+R); outside the window the defaults are used,
or `--set` on the command line: pycodecad export tray.py tray.stl --set width=120
"""
from typing import Annotated

from build123d import Axis, Box, Pos, fillet
from pytypehint import Description, Label, Max, Min, Slider
from pycodecad import expose, show


def tray(width: Annotated[float, Min(20.0), Max(200.0), Slider(), Label("Width")] = 80.0,
         depth: Annotated[float, Min(20.0), Max(200.0), Slider(), Label("Depth")] = 60.0,
         height: Annotated[float, Min(5.0), Max(100.0), Slider(), Label("Height")] = 25.0,
         wall: Annotated[float, Min(0.8), Max(5.0), Label("Wall"),
                         Description("Also the thickness of the floor")] = 2.0,
         rounded: Annotated[bool, Label("Rounded corners")] = True):
    """A box without lid: the outside measures width x depth x height, the floor is one wall thick."""
    outside = Pos(0, 0, height / 2) * Box(width, depth, height)
    inside = Pos(0, 0, wall + height / 2) * Box(width - 2 * wall, depth - 2 * wall, height)
    if rounded:
        outside = fillet(outside.edges().filter_by(Axis.Z), radius=min(width, depth) / 8)
        inside = fillet(inside.edges().filter_by(Axis.Z), radius=max(min(width, depth) / 8 - wall, 0.5))
    return outside - inside


show(expose(tray), name="tray", color="#4C9BE8")
