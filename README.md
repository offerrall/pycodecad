# pycodecad

Code-CAD with [build123d](https://github.com/gumyr/build123d): write a Python script, see the part,
export it for 3D printing.

A desktop window shows the files of a part, its code and parameters next to the 3D view, and runs
the script only when you press Run. The same script runs from the command line, so an AI assistant
can check its own work with `check` and `render`.

![The pycodecad window: the files of the folder, parameters and code on the left, a gear in the 3D view on the right](docs/images/window.png)

```python
from build123d import Box, Cylinder
from pycodecad import show

plate = Box(40, 30, 8) - Cylinder(5, 8)
show(plate, name="plate", color="#F4B02A")
```

The full documentation is at https://offerrall.github.io/pycodecad/.

## Documentation

- [Overview](https://offerrall.github.io/pycodecad/): what pycodecad gives you, its requirements and credits.
- [Getting started](https://offerrall.github.io/pycodecad/getting-started/): a first part, run, save, export.
- [The window](https://offerrall.github.io/pycodecad/window/): layout, Run and Save, folders, read-only mode, the 3D view, shortcuts.
- [Parameters](https://offerrall.github.io/pycodecad/parameters/): `expose()`, its controls and `--set`.
- [Scripts](https://offerrall.github.io/pycodecad/scripts/): `show`, `clear`, `frame` (animations), `import_mesh`, paths, errors.
- [Command line](https://offerrall.github.io/pycodecad/cli/): `examples`, `check`, `render`, `export`, `context`, exit codes.
- [Working with an AI assistant](https://offerrall.github.io/pycodecad/ai/): the AI context and how an assistant checks its work.
- [Files pycodecad writes](https://offerrall.github.io/pycodecad/files/): everything pycodecad writes, and where.
- [Embedding pycodecad in your app](https://offerrall.github.io/pycodecad/embedding/): the window's parts in your own app (experimental).
- [Design](https://offerrall.github.io/pycodecad/design/): the principles and what follows from them.
- [Limitations](https://offerrall.github.io/pycodecad/limitations/): platforms, graphics and Python requirements, what is not supported.

### Maintaining

- [Development](https://offerrall.github.io/pycodecad/development/): tests, type checks and releases.
- [Benchmarks](https://offerrall.github.io/pycodecad/benchmarks/): measuring a Run and the window's drawing, with reference numbers.
