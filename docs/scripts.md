# Scripts

A pycodecad script is a plain Python file that builds shapes with
[build123d](https://build123d.readthedocs.io) and says what is in the scene with `show()`. The
window, `check`, `render` and `export` all look at that same scene.

```python
from pycodecad import show, clear, frame, import_mesh, expose
```

## show

```python
show(*objs, name=None, color=None)
```

Adds build123d shapes, builders (`BuildPart`, `BuildSketch`, `BuildLine`), meshes from
`import_mesh()`, or lists of them, to the scene.

```python
show(plate, name="plate", color="#F4B02A")
show(bracket)                         # a BuildPart works too
show([bolt_a, bolt_b], name="bolt")   # bolt_1 and bolt_2
```

- `name` labels the object in exports and in `check`; with several objects they are numbered
  (`bolt_1`, `bolt_2`). Without it, the type and the position in the scene: `Part 1`, `Solid 2`...
- `color` is `"#RRGGBB"`, a basic name (`red`, `green`, `blue`, `gold`, `violet`, `purple`,
  `white`, `black`, `gray`, `orange`, `yellow`, `cyan`, `magenta`) or an RGB triple in 0..1 or
  0..255 (`(0.2, 0.6, 0.9)`, `(50, 150, 230)`). Without it, a color from a small palette.
- Anything else (a number, an empty shape, a bad color) is an error on that line.

Without `show()` the scene is empty: `check` warns "Nothing shown", the window says so, and `render`
and `export` fail.

## clear

`clear()` removes everything shown so far.

## frame

`frame()` saves the scene as it is now as the next frame of an animation. The window plays the
frames at 30 per second, with play/pause and a slider under the 3D view; without any `frame()`
the scene is a still one. The scene stays after `frame()`: `clear()` it yourself.

```python
carriage = build_carriage()               # built once
for i in range(60):
    x = 150 * i / 59
    clear()
    show(bench, name="bench")
    show(Pos(x, 0, 0) * carriage, name="carriage")
    frame()
```

To hold a pose, call `frame()` several times (30 calls are one second). A shape moved with `Pos` or
`Rot` is not computed again: pycodecad tessellates each different shape once per run, so frames of
parts that only move are cheap. A shape that changes (a new boolean each frame) costs its
computation in every frame. `render --frame N` draws one frame; `check` reports how many there are.

## import_mesh

```python
import_mesh(path, solid=False, max_faces=5000)
```

Reads an STL or 3MF file.

- `solid=False` (default): a fast mesh you can `show()` and export as STL, 3MF or GLB. It cannot be
  used in booleans, and a scene with meshes cannot be exported as STEP or BREP.
- `solid=True`: a build123d `Solid` you can use in booleans. Only for small closed meshes: more
  than `max_faces` triangles is an error, because booleans on big meshes are extremely slow.

```python
reference = import_mesh("pyramid.stl")                # to look at, next to your part
solid = import_mesh("knob.stl", solid=True)           # to cut or join
show(Box(30, 30, 10) - solid)
```

## expose

`expose(fn)` turns the parameters of a function into controls in the window. See
[Parameters](parameters.md).

## Folders, helper modules and assets

A script always runs from its own folder: that folder is the working directory and comes first in
`sys.path`. So a part works on any PC when you keep it together:

```text
tray/
  tray.py          # import helper, import_svg("logo.svg")
  helper.py
  logo.svg
```

- `import helper` finds `helper.py` next to the script. Every run is a fresh process, so edits to
  helper modules are always picked up (and no `__pycache__` is written for them).
- Use relative paths like `import_svg("logo.svg")`, never absolute ones. pycodecad warns about
  absolute paths into your home folder.
- Anything missing is the normal Python error, with its traceback and line.

Examples: [parts.py](https://github.com/offerrall/pycodecad/blob/main/examples/parts.py) holds loose parts (one function each),
[gearbox.py](https://github.com/offerrall/pycodecad/blob/main/examples/gearbox.py) composes them and [assembly.py](https://github.com/offerrall/pycodecad/blob/main/examples/assembly.py) shows the result; [import_files.py](https://github.com/offerrall/pycodecad/blob/main/examples/import_files.py) extrudes an SVG
next to an STL.

## Plain python

`python part.py` runs a script without pycodecad: `show()`, `clear()` and `frame()` do nothing and `expose()`
calls the function with its defaults. Everything else, `import_mesh()` included, works as usual.

Plain `python` starts relative paths from the current directory, not the script's folder. For
files that must also work that way, build the path from the script:

```python
from pathlib import Path

assets = Path(__file__).parent / "assets"
logo = import_svg(assets / "logo.svg")
```

## Output

What the script prints is shown under the code in the window, and in the `stdout` field of
`check` (the end of it, when it is long). `sys.exit()` and `sys.exit(0)` end a script normally.

## Errors

When a script fails, pycodecad shows:

- the error message,
- where it happened: the file and line in your own code (the script or a helper module next to it),
- the traceback of your own files only (library frames between them are left out).

In the window the line is marked in the editor (in another file of the folder, a click on "in
helper.py, line 7" opens it there), and the last good objects stay on screen. `check`
puts the same in its JSON (`error`, `where`, `traceback`); `render` and `export` print it on stderr
and exit with 1. See [Command line](cli.md#exit-codes).
