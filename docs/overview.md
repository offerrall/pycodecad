# Overview

A part is one plain Python script that builds shapes with build123d and passes them to `show()`.
pycodecad opens a window on it, runs it in a fresh child process, and exports what it shows. The
window, the command line and an AI assistant all look at the same scene, so what an assistant checks
is what you see and what you print.

## What you get

- **A window** on a part: its files, the code and the part side by side. It runs the part once when
  it opens, then only when you press Run, and writes only when you press Save. Errors point at the
  line, and the last good part stays on screen. See [The window](window.md).
- **Parameters**: `expose(fn)` turns the arguments of a function into sliders, number boxes and
  checkboxes. See [Parameters](parameters.md).
- **Animations**: `frame()` saves the scene as a frame; the window plays them. Parts built once and
  moved with `Pos` are not computed again, so mechanisms play in real time. See
  [Scripts](scripts.md#frame).
- **A command line**: `check`, `render` and `export` run the same script without a window, and
  `pycodecad examples` copies the bundled examples to a folder and opens them. See
  [Command line](cli.md).
- **An AI workflow**: an assistant edits the file and checks its own work with `check` and
  `render`, which draws the part from several views in one picture. See
  [Working with an AI assistant](ai.md).
- **Exports** to STL, 3MF (also a profile for Bambu Studio), STEP, GLB and BREP, from the window or
  the command line.
- **Parts for your own app** (experimental): the window's code, parameters and 3D view as Dear
  ImGui components, in `pycodecad.embed`. See [Embedding pycodecad in your app](embedding.md).

pycodecad is small on purpose: thin glue over well-tested libraries, readable in an afternoon. See
[Design](design.md#small-on-purpose).

## Requirements

A graphics card with OpenGL 3.3. Linux is the native, tested platform; Windows and macOS are
compatible targets, with the differences listed in [Limitations](limitations.md).

## Credits

- [build123d](https://github.com/gumyr/build123d): the modeling language
- [Open CASCADE](https://dev.opencascade.org/) and [OCP](https://github.com/CadQuery/OCP): the geometry kernel
- [Dear ImGui](https://github.com/ocornut/imgui) and [slimgui](https://github.com/nurpax/slimgui): the interface
- [ModernGL](https://github.com/moderngl/moderngl), [GLFW](https://www.glfw.org/) and
  [pyGLFW](https://github.com/FlorianRhiem/pyGLFW): rendering and windows
- [NumPy](https://numpy.org/): meshes
- [pytypehint](https://offerrall.github.io/pytypehint/): the parameters of `expose()`
- [Lucide](https://lucide.dev): icons (ISC)
