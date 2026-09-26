"""The "AI context": a text to paste into an AI assistant so it can build and iterate on the part.

Used by the "Copy AI context" button and by `pycodecad context file.py`.
"""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

from . import __version__

SKIP = {"__pycache__", "venv", ".venv", "node_modules"}
MAX_FILES = 60
WINDOWS = sys.platform == "win32"

GUIDE = """\
## How pycodecad runs a script
- `{pycodecad} {file}` runs it in the window; `python {file}` runs it without one (show(), clear() and frame()
  then do nothing).
- A part always starts from its own folder, so it works on any PC: keep the script, its helper
  modules and its assets together in one folder and use relative paths, never absolute ones
  (/home/...). With plain `python`, relative paths start from the current directory: for files
  that must also work that way use `Path(__file__).parent / "name"`.
- Every run (window, check, render, export) writes its result to .pycodecad/{name}.last-run.json
  next to the script (same JSON as `check`): read it to see the latest error.

## Workflow
- Edit the file directly. The window runs the script once when it opens, then never reloads or
  runs by itself: it shows "Changed on disk" and the owner presses Reload and Run.
- Check your work from a terminal in that folder (each command runs the script fresh, no window):
    {pycodecad} check {file}        # JSON: ok, error, where (file:line), traceback, stdout, objects
    {pycodecad} render {file} out.png --views iso,front,top,right   # then look at out.png
    {pycodecad} render {file} out.png --views window                # exactly what the owner sees
    {pycodecad} render {file} out.png --set width=80                # other values for expose()
    {pycodecad} export {file} {stl}    # also .3mf .step .glb .brep; --profile bambu (Bambu Studio 3MF)
- Helper modules: write helper.py next to the script and `import helper` (fresh on every run).

## pycodecad API (docs: https://github.com/offerrall/pycodecad/tree/v{version}/docs)
`from pycodecad import show, clear, frame, import_mesh, expose`
The script says what is in the scene with show(); the window, check, render and export all look
at that same scene. Nothing is shown without show().
- show(*objs, name=None, color=None): add shapes/builders/lists to the scene. color: "#RRGGBB",
  a name ("red", "gold"...) or an RGB triple.
- clear(): empty the scene.
- frame(): save the scene now as the next frame of an animation (30/s; the window plays them).
  Build parts once and move them with Pos/Rot per frame (not recomputed); hold = call frame() again.
  `{pycodecad} render {file} out.png --frame N` draws frame N (1-based); check reports "frames".
- import_mesh(path, solid=False, max_faces=5000): STL/3MF as a fast mesh for show/export;
  solid=True gives a build123d Solid for booleans (small closed meshes only).
- expose(fn): calls fn and returns its result; the window shows a control per parameter (Run
  applies them). Only int/float/bool/str parameters with a default, annotated only with pytypehint
  Min, Max, Step, Slider, Label, Description: `def box(width: Annotated[float, Min(20.0),
  Max(200.0), Slider()] = 60.0)`, then `show(expose(box))`. Without the window the defaults are
  used, or `--set width=80` (or `box.width=80`) on check/render/export.

## build123d essentials (docs: https://build123d.readthedocs.io), units mm, Z up
```python
from build123d import *
from pycodecad import show

# Algebra style: shapes are values; + union, - cut, & intersect; Pos/Rot place them.
plate = Box(60, 40, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))  # sits on Z=0
plate -= Pos(20, 10, 0) * Cylinder(3, 20)            # through hole
plate = fillet(plate.edges().filter_by(Axis.Z), radius=4)

# Builder style: 2D sketch on a plane, then extrude.
with BuildPart() as bracket:
    with BuildSketch(Plane.XY):
        RectangleRounded(40, 20, 3)
        with Locations((-12, 0), (12, 0)):
            Circle(2.5, mode=Mode.SUBTRACT)
    extrude(amount=4)
    chamfer(bracket.edges().group_by(Axis.Z)[-1], length=0.8)  # top edges

show(Pos(0, 50, 0) * plate, name="plate", color="#F4B02A")
show(bracket, name="bracket")
```
- Primitives are centered on their location by default; use `align=` to put a face on a plane.
- Edge/face selection: `.edges().filter_by(Axis.Z)`, `.faces().sort_by(Axis.Z)[-1]` (top face),
  `.group_by(Axis.Z)[-1]`. Apply fillets/chamfers last; a radius too big for a wall fails.
- Other useful pieces: Text("ABC", font_size=8) in a BuildSketch, revolve(), loft(), sweep(),
  PolarLocations(r, n), GridLocations(dx, dy, nx, ny), mirror(about=Plane.YZ), offset(), import_svg().
"""


def quote(text: str) -> str:
    """A literal argument for PowerShell on Windows, or a POSIX shell elsewhere."""
    return "'" + text.replace("'", "''") + "'" if WINDOWS else shlex.quote(text)


def pycodecad_command() -> str:
    """How to call this pycodecad from a terminal."""
    script = Path(sys.executable).with_name("pycodecad.exe" if WINDOWS else "pycodecad")
    if script.exists():
        if shutil.which("pycodecad") == str(script):
            return "pycodecad"
        command = quote(str(script))
    else:
        command = f"{quote(sys.executable)} -m pycodecad"
    return "& " + command if WINDOWS else command


def size_text(size: float) -> str:
    if size < 1024:
        return f"{size:.0f} B"
    return f"{size / 1024:.1f} KB" if size < 1024**2 else f"{size / 1024**2:.1f} MB"


def folder_listing(folder: Path) -> list[str]:
    """Files of the folder and its subfolders (two levels), with sizes."""
    lines = []
    for path in sorted(folder.glob("*")) + sorted(folder.glob("*/*")):
        relative = path.relative_to(folder)
        if any(part.startswith(".") or part in SKIP for part in relative.parts) or not path.is_file():
            continue
        lines.append(f"  {relative.as_posix()} ({size_text(path.stat().st_size)})")
    if len(lines) > MAX_FILES:
        lines = lines[:MAX_FILES] + [f"  ... and {len(lines) - MAX_FILES} more"]
    return lines


def state_lines(state) -> list[str]:
    """State: anything with shown, error, error_file, error_line, warnings and stdout (Workspace or runner.Result)."""
    lines = []
    for obj in state.shown:
        bbox = obj.bbox()
        size = " x ".join(f"{hi - lo:.4g}" for lo, hi in zip(*bbox)) if bbox else "empty"
        position = ", ".join(f"{(lo + hi) / 2:.4g}" for lo, hi in zip(*bbox)) if bbox else "-"
        volume = f", volume {obj.volume:.6g} mm³" if obj.volume is not None else ""
        lines.append(f"- {obj.name}: size {size} mm, center ({position}){volume}")
    if not lines:
        lines.append("- no objects")
    if state.error:
        where = f" in {state.error_file}, line {state.error_line}" if state.error_file else ""
        lines.append(f"Error{where}:\n```\n{state.error.strip()[-2000:]}\n```")
    for warning in state.warnings:
        lines.append(f"Warning: {warning}")
    if state.stdout.strip():
        lines.append(f"Script output:\n```\n{state.stdout.strip()[-1500:]}\n```")
    return lines


def parameter_lines(exposed) -> list[str]:
    """The parameters of the exposed functions (params.Exposed) with the values the run used."""
    lines = []
    for group in exposed:
        lines.append(f"- {group.function}():")
        for param in group.params:
            limits = "length " if param.kind == "str" and (param.min is not None or param.max is not None) else ""
            if param.min is not None or param.max is not None:
                low = "" if param.min is None else f"{param.min:g}"
                high = "" if param.max is None else f"{param.max:g}"
                limits += f"{low}..{high}"
            extras = [param.kind, limits, param.step is not None and f"step {param.step:g}",
                      param.slider and "slider", param.label and f"label {param.label!r}",
                      param.value != param.default and f"default {param.default!r}"]
            text = f"  - {param.name} = {param.value!r} ({', '.join(filter(None, extras))})"
            lines.append(text + (f": {param.description}" if param.description else ""))
    return lines


def ai_context(path: Path, state=None) -> str:
    """The whole text. path: the script; state: see state_lines."""
    head = ["# pycodecad: code-CAD with build123d",
            f"A pycodecad window shows in 3D what `{path.name}` builds.",
            f"Folder: {path.parent}", f"File: {path}", "Files in the folder:", *folder_listing(path.parent)]
    if WINDOWS:
        head += ["", "Run the commands below in PowerShell."]
    if state is not None:
        head += ["", "## Current state", *state_lines(state)]
        exposed = getattr(state, "parameters", None) or []
        if exposed:
            head += ["", "## Exposed parameters (values of the last run)", *parameter_lines(exposed)]
    commands = dict(file=quote(path.name), name=path.name, stl=quote(path.stem + ".stl"),
                    pycodecad=pycodecad_command(), version=__version__)
    return "\n".join(head) + "\n\n" + GUIDE.format(**commands)
