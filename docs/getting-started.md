# Getting started

## Install

pycodecad needs Python 3.12 or later and a graphics card with OpenGL 3.3.

Linux is the native, tested platform; Windows and macOS are compatible targets, with native
testing pending. On Windows x64 and Apple silicon use Python 3.12 or 3.13 for prebuilt dependencies.
See [Platforms](design.md#platforms) for Intel Macs, other Python versions and platform differences.

```bash
pip install pycodecad
```

From source:

```bash
git clone https://github.com/offerrall/pycodecad
cd pycodecad
pip install .
```

Check it works:

```bash
pycodecad --version
```

## A first part

Open a window on a file. If the file does not exist, pycodecad creates it from a small example:

```bash
pycodecad part.py
```

A part can also be several files in one folder (`gear.py` imports `teeth.py`): open the folder
with `pycodecad gear/` and switch between its files in the window. See
[The window](window.md#a-part-in-several-files).

A part is a plain Python script that builds shapes with build123d and passes them to `show()`:

```python
from build123d import Axis, Box, Cylinder, fillet
from pycodecad import show

plate = Box(40, 30, 8) - Cylinder(5, 8)
plate = fillet(plate.edges().filter_by(Axis.Z), radius=3)
show(plate, name="plate", color="#F4B02A")
```

Units are millimetres and Z points up. Only what you pass to `show()` is in the scene: see
[Scripts](scripts.md).

## Run and save

The script runs once when the window opens. After that, nothing happens by itself:

1. Edit the code.
2. Press **Run** (Ctrl+R or F5) to see the result.
3. Press **Save** (Ctrl+S) when you like it.

If the script fails, the window shows the error with its line, and the last good part stays on
screen. More in [The window](window.md).

## Export

In the window, **Export** writes the part next to the script (`part.stl`, `part.3mf`...). From a
terminal:

```bash
pycodecad export part.py part.stl
pycodecad export part.py part.3mf --profile bambu    # 3MF for Bambu Studio, with names and colors
```

Formats: STL, 3MF, STEP, GLB and BREP. See [Command line](cli.md).

## Without pycodecad

`python part.py` also runs the script: `show()`, `clear()` and `frame()` then do nothing and `expose()` uses
the defaults. See [Scripts](scripts.md#plain-python).

## Next

- Try the [examples](../examples/): `pycodecad examples` copies them to `./pycodecad-examples` (once)
  and opens the folder: loose parts in `parts.py`, composed in `gearbox.py` and shown in `assembly.py`, turning in
  `gears_turning.py`.
- Make a part to measure with [Parameters](parameters.md).
- Let an assistant work on it: [Working with an AI assistant](ai.md).
