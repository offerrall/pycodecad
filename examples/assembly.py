"""The gearbox of gearbox.py: parts from parts.py composed with normal imports."""
from pycodecad import show

from gearbox import gearbox

for name, parts, color in gearbox():
    show(parts, name=name, color=color)
