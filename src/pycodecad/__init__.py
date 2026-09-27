"""Code-CAD with build123d: write a Python script, see the part, export it."""
from typing import TYPE_CHECKING

__version__ = "1.1.0"

__all__ = ["show", "clear", "frame", "import_mesh", "expose"]

if TYPE_CHECKING:
    from .api import clear, expose, frame, import_mesh, show


def __getattr__(name: str):
    # Lazy, so `import pycodecad` (and the CLI) start instantly.
    if name in __all__:
        from . import api

        return getattr(api, name)
    raise AttributeError(name)
