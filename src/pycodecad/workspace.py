"""A Workspace: the .py files of one folder, with the code, parameters, runs and 3D view of its
main file, drawn as an ImGui component (the whole pycodecad window is one; experimental in 1.0 for
other apps, see docs/embedding.md).

One file is edited at a time; Run always runs the main file (the part), which may import the
others (helper modules), with the editor's text for the one being edited. Nothing happens by
itself: a file is written only on Save and, after the first run at opening, the script runs only
on Run. When someone else changes the edited file (another editor, an AI assistant) the workspace
says so and offers Reload. Scripts run in child processes (see runner.py).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import glfw

from .api import FPS
from . import runner, sidecar, textedit, ui, window
from .cad import Shown
from .params import LIMIT, Exposed, Param
from .viewer import Viewer

WATCH_EVERY = 0.5  # seconds between checks of the file on disk
NEW_SCRIPT = """from build123d import *
from pycodecad import show

with BuildPart() as part:
    Box(40, 30, 10)
    fillet(part.edges().filter_by(Axis.Z), radius=4)
    Hole(radius=5)

show(part, name="part")
"""


ZOOMS = (0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)  # code zoom steps, like browsers
preloading = threading.Thread(target=runner.preload, daemon=True)  # build123d takes a second or two to import


def python_files(folder: Path) -> list[Path]:
    """The .py files of a folder (not its subfolders), by name, without hidden ones: names that start
    with "." or "_" (tools, scratch, private helpers) stay out of the list."""
    try:
        return sorted(path for path in folder.iterdir()
                      if path.suffix == ".py" and not path.name.startswith((".", "_")) and path.is_file())
    except OSError:
        return []


def input_stamp(folder: Path, skip: set[str]) -> dict[str, tuple[int, int]]:
    """Modification time and size of every file a run may read: the folder and its subfolders but
    hidden ones, __pycache__, virtual environments and the paths in skip. Export runs the code
    again, so it needs these files as they were at Run."""
    stamp = {}
    for root, dirs, names in os.walk(folder):
        dirs[:] = [name for name in dirs if not name.startswith(".") and name != "__pycache__"
                   and not os.path.exists(os.path.join(root, name, "pyvenv.cfg"))]
        for name in names:
            path = str(Path(root) / name)
            if name.startswith(".") or path in skip:
                continue
            if (signature := file_signature(path)) is not None:
                stamp[path] = signature
    return stamp


def file_signature(path: str) -> tuple[int, int] | None:
    """Modification time and size of a file, None when it cannot be read."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


def find_main(folder: Path) -> Path:
    """The part of a folder: the first .py file that calls show(), else the first one, else part.py."""
    files = python_files(folder)
    for path in files:
        try:
            if "show(" in sidecar.read_script(path):
                return path
        except OSError:
            continue
    return files[0] if files else folder / "part.py"


Job = tuple[Path, str, dict[str, str]]  # a run: the main file, its code, {helper file: unsaved text}

class Workspace:
    """path: the main file, or a folder (its main is find_main's). A missing main is created
    from an example (not when read_only). read_only (--read-only): an order form for scripts that
    must never change: the code is not shown and no script is written; choose() picks the file to
    run, and Run always runs it as it is on disk. run: run the main once, as soon as build123d is loaded. Opening raises OSError (with a
    readable message) when the file cannot be used: a missing folder, a file that is not UTF-8.

    draw() shows it in the current ImGui region between Window.frame() calls (and updates it:
    finished runs, the files on disk). A Workspace that is not drawn: call update() every frame."""

    def __init__(self, path: str | Path, read_only: bool = False, run: bool = True):
        path = Path(path).resolve()
        self.main = find_main(path) if path.is_dir() else path  # Run runs it; see set_main()
        if not self.main.exists() and not read_only:
            self.main.write_text(NEW_SCRIPT, encoding="utf-8")
        self.read_only = read_only
        self.show_files = True  # draw the list of the folder's files
        self.load(self.main)  # the edited file: path, editor...
        self.file_list = python_files(self.folder)
        self.opening: tuple[Path, int | None] | None = None  # asked to open while the editor had unsaved changes
        self.save_as_open = False  # the Save as dialog is showing
        self.save_as_name = ""
        self.next_watch = 0.0

        self.shown: list[Shown] = []  # objects on screen (from the last successful run)
        self.frames: list[list[Shown]] = []  # the animation of the last successful run (frame() calls)
        self.playing = True
        self.clock = 0.0  # seconds into the animation
        self.ticked = time.monotonic()
        self.child: runner.Run | None = None
        self.run_started = 0.0
        self.run_requested = run  # started by update() once build123d is loaded
        self.error: str | None = None
        self.error_file: str | None = None  # where the error happened: the script or a helper module
        self.error_line: int | None = None
        self.warnings: list[str] = []
        self.stdout = ""
        self.duration: float | None = None
        # Parameters of exposed functions: what the last successful run used, and the values changed in the
        # panel ("function.param" -> value). They are only in memory and reach the script on Run.
        self.parameters: list[Exposed] = []
        self.values: dict[str, object] = {}
        self.child_job: Job | None = None  # what the running child runs (see run_job)
        self.child_values: dict[str, object] = {}  # the parameter values sent to it
        # What is on screen: the main, code, sources and parameter values of the last good run; Export
        # exports exactly this, even after the editor, the values or the main changed.
        self.shown_job: tuple[Job, dict[str, object], dict[str, tuple[int, int]]] | None = None
        self.child_stamp: dict[str, tuple[int, int]] = {}  # input_stamp at the start of the child
        self.written: dict[str, tuple[int, int]] = {}  # file_signature of the exports and pictures written
        self.exports: list[runner.Run] = []
        self.stopped: list[runner.Run] = []  # killed runs still writing their final last-run file
        self.message = ""  # last status message
        self.message_is_error = False

        self.viewer = Viewer()
        self.camera_saved: tuple | None = None
        self.camera_changed_at = 0.0
        self.split = 0.38  # fraction of the width used by the code
        self.code_zoom = 1.0  # size of the code text (Ctrl + / Ctrl - / Ctrl 0), one of ZOOMS
        self.closed = False
        if not preloading.ident:
            preloading.start()
        window.components.add(self)

    # --- in the frame loop ------------------------------------------------------------------------

    def draw(self) -> None:
        self.update()
        ui.workspace(self, window.active().events)

    def close_prompt(self, host: window.Window) -> None:
        """Draw the Save / Discard / Cancel prompt when the user closed the window with unsaved
        changes (host.frame(keep_open=self.dirty()) keeps it open meanwhile); Save or Discard closes it."""
        ui.close_prompt(self, host)

    def frame_index(self) -> int:
        return int(self.clock * FPS) % len(self.frames) if self.frames else 0

    def on_screen(self) -> list[Shown]:
        """What the view shows: the current frame of an animation, else the scene."""
        return self.frames[self.frame_index()] if self.frames else self.shown

    def seek(self, index: int) -> None:
        """Show this frame, paused."""
        self.clock, self.playing = index / FPS, False

    def update(self) -> None:
        """Start a requested run, collect finished ones, watch the file, remember the camera."""
        now = time.monotonic()
        if self.frames and self.playing:
            self.clock += now - self.ticked
            if window.current is not None:
                window.current.timeout = 0.0
        self.ticked = now
        if self.run_requested and not preloading.is_alive():
            self.run_requested = False
            self.start_run()
        self.check_runs()
        now = time.monotonic()
        if now >= self.next_watch:
            self.next_watch = now + WATCH_EVERY
            self.watch_file()
        self.save_camera(now)
        if window.current is not None and (self.child or self.exports or self.run_requested):
            window.current.timeout = min(window.current.timeout, window.BUSY)

    def close(self) -> None:
        """Kill the runs (waiting up to 2 s for them to record it) and free the view (Window.close()
        does it for every open Workspace)."""
        self.closed = True
        window.components.discard(self)
        runs = [run for run in [self.child, *self.exports, *self.stopped] if run is not None]
        for run in runs:
            run.kill()
        deadline = time.monotonic() + 2.0  # let them record "Stopped", but never hang the exit
        for run in runs:
            run.finished.wait(max(0.0, deadline - time.monotonic()))
        self.viewer.close()

    def wake(self) -> None:
        """Called from runner threads: make the loop look at finished runs now."""
        if not self.closed and window.current is not None:
            glfw.post_empty_event()

    def title(self) -> str:
        runs = f" (runs {self.main.name})" if self.path != self.main else ""
        return f"pycodecad - {self.path.name}{' *' if self.dirty() else ''}{runs}"

    @property
    def folder(self) -> Path:
        return self.main.parent

    def dirty(self) -> bool:
        """The editor has changes that are not saved to the file."""
        return self.editor.text != self.saved_text

    def say(self, message: str, error: bool = False) -> None:
        """Show a message in the status line (errors also in the open dialog)."""
        self.message, self.message_is_error = message, error

    # --- running the script --------------------------------------------------------------------

    def running(self) -> bool:
        """A run is going or about to start."""
        return self.child is not None or self.run_requested

    def ran(self) -> bool:
        """A run has finished (or was stopped) since the window opened."""
        return self.duration is not None or self.error is not None

    def zoom_code(self, step: int) -> None:
        """One zoom step in (+1) or out (-1), or back to 100% (0)."""
        index = ZOOMS.index(self.code_zoom) + step if step else ZOOMS.index(1.0)
        self.code_zoom = ZOOMS[max(0, min(len(ZOOMS) - 1, index))]

    def run(self) -> None:
        """Run the main file with the current values (at the next update), with the editor's text
        for the edited file (saved or not)."""
        self.run_requested = True

    def run_job(self) -> Job:
        """What Run runs: the main, its code, and {file: text} of the edited file when it is another
        one (a helper module the main may import). Raises OSError when the main cannot be read."""
        if self.read_only:  # nothing is edited: the file as it is now
            return self.main, sidecar.read_script(self.main), {}
        if self.path == self.main:
            return self.main, self.editor.text, {}
        return self.main, sidecar.read_script(self.main), {str(self.path): self.editor.text}

    def start_run(self) -> None:
        if self.child is not None:
            self.child.kill()  # a newer version of the code replaces the running one
            self.stopped.append(self.child)
            self.child = None
        try:
            self.child_job = self.run_job()
        except OSError as exc:
            self.error, self.error_file, self.error_line = f"Could not read {sidecar.error_text(exc)}", None, None
            return
        main, code, sources = self.child_job
        self.child_stamp = self.input_stamp(self.child_job)
        self.child_values = dict(self.values)
        self.child = runner.Run(code, str(main), on_done=self.wake, values=self.child_values, strict=False,
                                sources=sources)
        self.run_started = time.monotonic()

    def stop(self) -> None:
        if self.child is not None:
            self.child.kill()
            self.stopped.append(self.child)
            self.child = None
            self.error, self.error_file, self.error_line = "Stopped", None, None
            self.say("Stopped")

    def check_runs(self) -> None:
        self.stopped = [run for run in self.stopped if not run.done()]
        if self.child is not None and self.child.done():
            result, self.child = self.child.wait(), None  # finished: wait() returns at once
            if self.child_job is None or self.child_job[0] != self.main:
                return  # a run of the previous main (set_main while it ran): not this main's result
            self.stdout, self.duration = result.stdout, result.duration
            self.error, self.error_file, self.error_line = result.error, result.error_file, result.error_line
            self.warnings = result.warnings
            if result.error is None:  # on errors the last good objects (and parameters) stay on screen
                used = {f"{e.function}.{p.name}": p.value for e in result.parameters for p in e.params}
                self.shown_job = (self.child_job, used, self.child_stamp)
                self.set_parameters(result.parameters, used, self.child_values)
                self.shown = result.shown
                self.frames, self.clock, self.playing = result.frames, 0.0, True
                self.say(result.warnings[0] if result.warnings else "")
        for export in [run for run in self.exports if run.done()]:
            self.exports.remove(export)
            result = export.wait()
            error = result.error or (None if result.exported else "Nothing shown: call show() in the script")
            if result.exported and (signature := file_signature(result.exported)) is not None:
                self.written[result.exported] = signature
            self.say(error.splitlines()[-1] if error else f"Exported {result.exported}", error=bool(error))

    def export(self, extension: str, profile: str = "generic", target: str | Path | None = None) -> None:
        """Export what is on screen (in a run of its own; the status line says when it is written).
        target: the file (relative to the folder), by default the main's name with extension."""
        if self.shown_job is None:
            self.say("Nothing to export yet: Run the main file first", error=True)
            return
        (main, code, sources), used, stamp = self.shown_job
        target = self.folder / target if target else main.with_suffix(f".{extension}")
        if changed := self.changed_inputs(stamp):
            self.say(f"{Path(changed[0]).name} changed since the last run: Run again, then export", error=True)
            return
        self.exports.append(runner.Run(code, str(main), export=str(target), profile=profile,
                                       on_done=self.wake, values=used, strict=False, sources=sources))
        self.say(f"Exporting {target.name}...")

    # --- parameters of exposed functions -------------------------------------------------------

    def set_parameters(self, parameters: list[Exposed], ran: dict[str, object], sent: dict[str, object]) -> None:
        """The parameters a successful run exposed and the values it used (`ran`), for the values `sent`. A changed value is
        dropped when its parameter is gone or of another kind, or when the run did not take it (e.g.
        beyond a new Max): the control then shows what the run used. Never after a failed run: it
        may have stopped before an expose(), e.g. a syntax error while editing."""
        self.parameters = parameters

        def kept(key: str, value: object) -> bool:
            if key not in ran or type(ran[key]) is not type(value):
                return False
            return value == ran[key] or key not in sent or sent[key] != value  # changed during the run

        self.values = {key: value for key, value in self.values.items() if kept(key, value)}

    def value(self, function: str, param: Param) -> object:
        """What the control shows: the changed value, else the default."""
        return self.values.get(f"{function}.{param.name}", param.default)

    def set_value(self, function: str, param: Param, value: int | float | bool | str) -> None:
        """Change a value (kept within the parameter's limits); the script sees it on the next Run."""
        if param.kind == "str":
            value = cast(str, value)  # the text control gives a str
            value = value[:int(param.max)] if param.max is not None else value
        elif param.kind != "bool":
            kind = float if param.kind == "float" else int  # the type of param.default
            number = kind(value)
            if param.min is not None:
                number = max(number, kind(param.min))
            if param.max is not None:
                number = min(number, kind(param.max))
            value = min(max(number, kind(-LIMIT)), kind(LIMIT))
        self.values[f"{function}.{param.name}"] = value

    def reset(self, function: str) -> None:
        """Back to the defaults for one exposed function (on the next Run)."""
        self.values = {key: value for key, value in self.values.items() if not key.startswith(function + ".")}

    def values_changed(self) -> bool:
        """The panel differs from the values the last run used: Run to apply them."""
        return any(self.value(e.function, p) != p.value for e in self.parameters for p in e.params)

    def save_picture(self) -> None:
        target = self.main.with_suffix(".png")
        try:
            target.write_bytes(self.viewer.picture())
        except OSError as exc:
            self.say(f"Could not save the picture: {sidecar.error_text(exc)}", error=True)
            return
        if (signature := file_signature(str(target))) is not None:
            self.written[str(target)] = signature
        self.say(f"Saved {target}")

    # --- the files of the folder ---------------------------------------------------------------

    def files(self) -> list[Path]:
        """The .py files of the folder, by name (refreshed with the disk watch), with the edited
        and the main file even when they are not (yet) on disk."""
        return sorted({*self.file_list, self.path, self.main}, key=lambda path: path.name)

    def load(self, path: Path) -> None:
        """Edit this file (raises OSError when it cannot be read)."""
        mtime = self._mtime(path)  # before reading: a change in between is noticed later
        text = sidecar.read_script(path)
        self.path, self.editor = path, textedit.load(text)
        self.saved_text = text  # what the file holds, as far as we know
        self.file_mtime = mtime
        self.disk_changed = False  # someone else changed the file: offer Reload

    def open(self, path: str | Path, line: int | None = None) -> bool:
        """Edit another file (relative to the folder); Run still runs the main. line: put the
        cursor there (1 is the first line). Refused (False, with a message) while the editor has
        unsaved changes (save() or discard() first) or when the file cannot be read."""
        path = (self.folder / path).resolve()
        if path != self.path:
            if self.dirty():
                self.say(f"Unsaved changes in {self.path.name}: save or discard them first", error=True)
                return False
            try:
                self.load(path)
            except OSError as exc:
                self.say(f"Could not open {sidecar.error_text(exc)}", error=True)
                return False
            self.say("")
        if line is not None:
            at = textedit.offset(self.editor.text, line - 1, 0)
            self.editor = replace(self.editor, cursor=at, anchor=at, reveal=True)
        return True

    def set_main(self, path: str | Path) -> None:
        """Run runs this file from now on (relative to the folder). The parameters and values of
        the previous main are dropped; what is on screen (and what Export writes) stays until the
        next Run."""
        path = (self.folder / path).resolve()
        if path != self.main:
            self.main, self.parameters, self.values = path, [], {}
            self.camera_saved = None  # saved for the new main too

    def choose(self, path: str | Path) -> None:
        """Read only: run this file of the folder (relative to it) from now on, now."""
        if self.open(path):
            self.set_main(path)
            self.run()

    def discard(self) -> None:
        """Drop the editor's unsaved changes (Undo brings them back)."""
        self.editor = textedit.replace_all(self.editor, self.saved_text)

    # --- the edited file on disk ---------------------------------------------------------------

    def input_stamp(self, job: Job) -> dict[str, tuple[int, int]]:
        """input_stamp of the folder of job's main, without the main and sources (their text is in
        the job)."""
        main, _, sources = job
        return input_stamp(main.parent, {str(main), *sources})

    def changed_inputs(self, stamp: dict[str, tuple[int, int]]) -> list[str]:
        """The files that differ from the stamp of the run on screen. A file that did not exist at
        that Run and is still as this window wrote it (an export, a picture) is an output, not an
        input; any other change counts, also to a file this window wrote (it may be read)."""
        assert self.shown_job is not None
        now = self.input_stamp(self.shown_job[0])
        return sorted(path for path in now.keys() | stamp.keys() if now.get(path) != stamp.get(path)
                      and not (path not in stamp and self.written.get(path) == now.get(path)))

    @staticmethod
    def _mtime(path: Path) -> int | None:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    def save(self) -> bool:
        """Write the editor to the file. On failure the edits stay (unsaved) and the status says why."""
        if self.read_only:
            self.say("Read only: scripts are never written", error=True)
            return False
        return self._write(self.path)

    def save_as(self, target: str) -> bool:
        """Write the code to a new file and continue working on it (in normal mode). A copy of the
        main becomes the main."""
        if self.read_only:
            self.say("Read only: scripts are never written", error=True)
            return False
        new = (self.path.parent / target).resolve()
        if new.exists():
            self.say(f"{new.name} already exists: choose another name", error=True)
            return False
        if not self._write(new):
            return False
        if self.path == self.main:
            self.main = new
        self.path = new
        self.file_list = python_files(self.folder)
        self.say(f"Saved as {new}")
        return True

    def _write(self, path: Path) -> bool:
        text = self.editor.text
        try:
            mtime = sidecar.write_atomic(path, text)
        except OSError as exc:
            self.say(f"Could not save: {sidecar.error_text(exc)}", error=True)
            return False
        # The baseline is what was written: a change made right after it is still noticed.
        self.saved_text, self.file_mtime, self.disk_changed = text, mtime, False
        self.say(f"Saved {path.name}")
        return True

    def watch_file(self) -> None:
        """Notice (never apply) changes made to the edited file by someone else, and files that
        appear in or disappear from the folder."""
        self.file_list = python_files(self.folder)
        mtime = self._mtime(self.path)
        if mtime is None or mtime == self.file_mtime:
            return
        self.file_mtime = mtime
        try:
            text = sidecar.read_script(self.path)
        except OSError:
            return
        if text == self.editor.text:
            self.saved_text, self.disk_changed = text, False
        elif text != self.saved_text:
            self.disk_changed = True

    def reload(self) -> None:
        """Replace the editor text with the file (the editor's unsaved changes are lost)."""
        mtime = self._mtime(self.path)
        try:
            text = sidecar.read_script(self.path)
        except OSError as exc:
            self.say(f"Could not reload: {sidecar.error_text(exc)}", error=True)
            return
        self.editor = textedit.replace_all(self.editor, text)
        self.saved_text, self.file_mtime, self.disk_changed = text, mtime, False
        self.say(f"Reloaded {self.path.name}")

    # --- camera ----------------------------------------------------------------------------------

    def save_camera(self, now: float) -> None:
        """Write camera + view size next to the script, one second after they stop changing."""
        if self.viewer.fit_pending:
            return
        current = (self.viewer.camera, self.viewer.size)
        if current == self.camera_saved:
            return
        if self.camera_changed_at == 0.0:
            self.camera_changed_at = now
        elif now - self.camera_changed_at > 1.0:
            self.camera_changed_at = 0.0
            self.camera_saved = current
            try:
                sidecar.save_camera(self.main, self.viewer.camera, self.viewer.size)
            except OSError:
                pass  # a read-only folder: `render --views window` will say there is no camera
