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

- [Overview](docs/overview.md): what pycodecad gives you, its requirements and credits.
- [Getting started](docs/getting-started.md): a first part, run, save, export.
- [The window](docs/window.md): layout, Run and Save, folders, read-only mode, the 3D view, shortcuts.
- [Parameters](docs/parameters.md): `expose()`, its controls and `--set`.
- [Scripts](docs/scripts.md): `show`, `clear`, `frame` (animations), `import_mesh`, paths, errors.
- [Command line](docs/cli.md): `examples`, `check`, `render`, `export`, `context`, exit codes.
- [Working with an AI assistant](docs/ai.md): the AI context and how an assistant checks its work.
- [Files pycodecad writes](docs/files.md): everything pycodecad writes, and where.
- [Embedding pycodecad in your app](docs/embedding.md): the window's parts in your own app (experimental).
- [Design](docs/design.md): the principles and what follows from them.
- [Limitations](docs/limitations.md): platforms, graphics and Python requirements, what is not supported.

### Maintaining

- [Development](docs/development.md): tests, type checks and releases.
- [Benchmarks](docs/benchmarks.md): measuring a Run and the window's drawing, with reference numbers.
