# pycodecad

[![PyPI](https://img.shields.io/pypi/v/pycodecad)](https://pypi.org/project/pycodecad/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://pypi.org/project/pycodecad/)
[![Platform](https://img.shields.io/badge/platform-Linux%20native%20%7C%20Windows%20%26%20macOS%20compatible-lightgrey)](docs/design.md#platforms)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Code-CAD with [build123d](https://github.com/gumyr/build123d): write a Python script, see the part,
export it for 3D printing.

![The pycodecad window: the files of the folder, parameters and code on the left, a gear in the 3D view on the right](docs/images/window.png)

```python
from build123d import Box, Cylinder
from pycodecad import show

plate = Box(40, 30, 8) - Cylinder(5, 8)
show(plate, name="plate", color="#F4B02A")
```

## Install

```bash
pip install pycodecad        # Python 3.12+, OpenGL 3.3
```

## Quick start

```bash
pycodecad examples                    # copy the examples to ./pycodecad-examples and open them
pycodecad part.py                     # a window on part.py (created from an example if missing)
pycodecad parts/gear/                 # a window on a folder: a part in several files
pycodecad check part.py               # run it without a window, print the result as JSON
pycodecad export part.py part.stl     # also .3mf .step .glb .brep
```

## What you get

- **A window** on a part: its files, the code and the part side by side. It runs the part once when
  it opens, then only when you press Run, and writes only when you press Save.
- **Parameters**: `expose(fn)` turns the arguments of a function into sliders, number boxes and
  checkboxes.
- **Animations**: `frame()` saves the scene as a frame; the window plays them. Parts built once and
  moved with `Pos` are not computed again, so mechanisms play in real time.
- **A command line**: `check`, `render` and `export` run the same script without a window.
- **An AI workflow**: an assistant edits the file and checks its own work with `check` and
  `render`.
- **Parts for your own app** (experimental): the window's code, parameters and 3D view as Dear
  ImGui components, in `pycodecad.embed`.

<table>
  <tr>
    <td width="33%"><img src="docs/images/parameters.png" alt="The Parameters panel: sliders, a number box and a checkbox made by expose()"></td>
    <td width="33%"><img src="docs/images/error.png" alt="A failed run: the line marked in the editor and the traceback under it"></td>
    <td width="33%"><img src="docs/images/render-grid.png" alt="pycodecad render: a gear in iso, front, top and right views"></td>
  </tr>
  <tr>
    <td align="center">Parameters from <code>expose()</code></td>
    <td align="center">Errors point at the line</td>
    <td align="center"><code>pycodecad render</code>: what an AI sees</td>
  </tr>
</table>

pycodecad is small on purpose, readable in an afternoon: see [Design](docs/design.md#small-on-purpose).

## Documentation

- [Getting started](docs/getting-started.md): install, a first part, run, export.
- [The window](docs/window.md): layout, Run and Save, Reload, read-only mode, shortcuts.
- [Parameters](docs/parameters.md): `expose()`, its controls and `--set`.
- [Scripts](docs/scripts.md): `show`, `clear`, `frame` (animations), `import_mesh`, colors, paths, errors.
- [Command line](docs/cli.md): `check`, `render`, `export`, `context`, exit codes.
- [Working with an AI assistant](docs/ai.md): the AI context and how an assistant checks its work.
- [Files](docs/files.md): everything pycodecad writes, and where.
- [Embedding](docs/embedding.md): the window's parts in your own app (experimental).
- [Design](docs/design.md): principles, platforms and plans.
- [Development](docs/development.md): tests, type checks and releases.
- [Benchmarks](docs/benchmarks.md): measuring a Run and the window's drawing, and the latest review.

Examples: [examples/](examples/)

## Credits

- [build123d](https://github.com/gumyr/build123d): the modeling language
- [Open CASCADE](https://dev.opencascade.org/) and [OCP](https://github.com/CadQuery/OCP): the geometry kernel
- [Dear ImGui](https://github.com/ocornut/imgui) and [slimgui](https://github.com/nurpax/slimgui): the interface
- [ModernGL](https://github.com/moderngl/moderngl), [GLFW](https://www.glfw.org/) and
  [pyGLFW](https://github.com/FlorianRhiem/pyGLFW): rendering and windows
- [NumPy](https://numpy.org/): meshes
- [pytypehint](https://github.com/offerrall/pytypehint): the parameters of `expose()`
- [Lucide](https://lucide.dev): icons (ISC)

## License

[MIT](LICENSE)
