"""Extruded SVG next to a reference STL. The paths start from this file's folder, so the script
also works with plain `python examples/import_files.py` from any directory."""
from pathlib import Path

from build123d import extrude, import_svg
from pycodecad import import_mesh, show

assets = Path(__file__).parent / "assets"
height = 3.0

logo = extrude(import_svg(assets / "logo.svg"), amount=height)  # pyright: ignore[reportArgumentType]
show(logo, name="logo", color="gold")
show(import_mesh(assets / "pyramid.stl"), name="reference", color="blue")
