"""One loose part made to measure: expose() gives the window a slider per parameter of gear()."""
from pycodecad import expose, show

from parts import gear

show(expose(gear), name="gear", color="#F4B02A")
