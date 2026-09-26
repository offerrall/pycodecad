# Design

The ideas behind pycodecad, and what follows from them.

## One file, plain Python

A part is one Python script (plus, if you want, helper modules and assets in its folder). There is
no project file, no hidden state and no format of pycodecad's own: the script also runs with plain
`python`, and any editor or assistant can change it. See [Scripts](scripts.md).

## Explicit

Nothing happens by itself. The window runs the script once when it opens, then only on **Run**; it
writes the file only on **Save**; it notices changes on disk but reloads only on **Reload**.
Parameter values change a run only when you press Run, and are never written into the script. See
[The window](window.md).

## One scene

The script says what is in the scene with `show()`. The window, `check`, `render` and `export` all
look at that same scene, so what an assistant checks is what you see and what you print.

## A fresh child process per run

Every run is a new child process: on Linux a fork of pycodecad with build123d already imported, so it
starts at once. Because of that:

- a script can never break or freeze the window;
- **Stop** and Ctrl+C kill a run at once, whatever it is doing (on Linux with every process it
  started, and a run dies with pycodecad);
- edits to helper modules are always picked up;
- the export runs where the script ran, so it writes the real build123d shapes.

## Invariants in the types

The state that must hold is checked where it is built: parameters, exposed functions, the editor
and its undo history, the camera and the display are immutable models that cannot be built in a
state the window could not show. An impossible state is an error with a message, not a
half-working window.

## Small and native

A desktop window drawn with Dear ImGui and ModernGL on GLFW, no web view or server. Few
dependencies, and nothing written outside the files listed in [Files](files.md).

The window is built from parts: a Workspace (a folder: code, parameters, runs) and a Viewer (a 3D
view), drawn as ImGui components in a plain frame loop. Other apps can use the same parts
([Embedding](embedding.md), experimental in 1.0).

## Small on purpose

pycodecad is about 4,600 lines of Python: small enough to read in an afternoon. It aims to be robust by
being thin glue over well-tested libraries: build123d and Open CASCADE for the geometry, Dear ImGui
for the interface, ModernGL and GLFW for drawing and windows, pytypehint for validating parameters.
Its own code is covered by tests and type checked with pyright ([Development](development.md)).

## Platforms

Linux is the native platform: pycodecad is developed and tested there. Windows and macOS are
compatible targets; their code paths have been reviewed, with testing on those systems still
pending. Problems found there are fixed as they are reported.

On Windows and macOS each run starts a new Python process, so startup takes longer than on Linux.
Stop terminates that script, but does not reach processes the script started itself. On macOS the
shortcuts use Ctrl, as documented, rather than Cmd. Windows AI context commands use PowerShell.

Python 3.12+ and OpenGL 3.3 are required. Use Python 3.12 or 3.13 on Windows x64 and macOS Apple
silicon for installation with prebuilt dependencies; resolution has been checked for both.
With Python 3.14, ModernGL and glcontext currently need source builds on those platforms.
Intel Macs also require building
[slimgui](https://pypi.org/project/slimgui/0.8.3/#files) from source because it has no Intel macOS
wheel; a compiler is needed there.

## Animations as frames

An animation is not a second language: the script shows a scene and calls `frame()`, as many times as
it likes, and the window plays those scenes. Everything stays explicit (the script decides every
frame) and nothing new runs in the window. It is fast because moving a part is not computing it:
build123d moves a shape without recomputing it, and pycodecad tessellates each different shape once
per run, so a frame of moved parts is a list of placements.
