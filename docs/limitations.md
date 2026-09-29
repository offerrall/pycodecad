# Limitations

## Platforms

Linux is the native platform: pycodecad is developed and tested there. Windows and macOS are
compatible targets: their code paths are reviewed, not tested on those systems. Report problems
found there as issues.

On Windows and macOS:

- Each run starts a new Python process, so a run starts slower than on Linux, where it is a fork of
  pycodecad with build123d already imported.
- Stop terminates the script, but not processes the script started itself.
- The shortcuts use Ctrl, as documented, also on macOS (not Cmd).
- On Windows the commands in the AI context are for PowerShell.

## Graphics and installation

- The window and `render` need OpenGL 3.3.
- On Windows x64 and macOS Apple silicon, Python 3.12 and 3.13 install with prebuilt dependencies.
  With other Python versions, ModernGL and glcontext may need building from source.
- Intel Macs need [slimgui](https://pypi.org/project/slimgui/) built from source, because it has no
  Intel macOS wheel; a compiler is needed there.

## Meshes

A mesh from `import_mesh()` (without `solid=True`) cannot be used in booleans, and a scene with
meshes exports as STL, 3MF or GLB, not STEP or BREP. `import_mesh(..., solid=True)` refuses meshes
with more than `max_faces` triangles, because booleans on big meshes are extremely slow. See
[Scripts](scripts.md#import_mesh).

## Embedding

`pycodecad.embed` is experimental: its names and details may change in a minor version. One
`Window` per process, and 3MF imports belong inside the scripts the Workspace runs. See
[Embedding pycodecad in your app](embedding.md).
