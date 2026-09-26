"""An animation with frame(): the gearbox turning. The parts are built once (in gearbox.py) and
only placed in each frame, so 90 frames cost little more than one."""
from pycodecad import clear, frame, show

from gearbox import gearbox

for step in range(90):
    clear()
    for name, parts, color in gearbox(angle=360 * step / 90):
        show(parts, name=name, color=color)
    frame()
