"""Run a user script in a child process and get back what it shows.

Every run is a fresh child: on Linux a fork of the current process (build123d is already
imported, so a run starts instantly), elsewhere a new `python` process (macOS does not support
forking a process that has a window and threads). The child executes the
script from source with the script folder as working directory and first entry of sys.path,
tessellates what it shows, optionally exports, sends a `Result` back through a pipe and exits.
Stopping a run kills the child, and on Linux anything it started in its process group.

    run = Run(code, "/path/part.py")     # starts at once
    result = run.wait()                  # or poll run.done() from a UI loop
"""
from __future__ import annotations

import contextlib
import ctypes
import datetime
import importlib.machinery
import importlib.util
import io
import linecache
import os
import pickle
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import types
import warnings
from dataclasses import dataclass, field, replace

from .cad import Shown, hex_color
from .params import to_json

USE_FORK = sys.platform.startswith("linux")
PRCTL = ctypes.CDLL(None).prctl if sys.platform.startswith("linux") else None
STDOUT_LIMIT = 64 * 1024
NOTHING_SHOWN = "Nothing shown: call show(...)"


@dataclass
class Result:
    shown: list[Shown] = field(default_factory=list)
    frames: list[list[Shown]] = field(default_factory=list)  # the scenes frame() saved (an animation)
    stdout: str = ""
    error: str | None = None  # traceback of the user's code, "Stopped", or an export problem
    error_file: str | None = None  # the user file (script or helper module) where it happened
    error_line: int | None = None
    duration: float = 0.0
    exported: str | None = None  # path written by an export run
    warnings: list[str] = field(default_factory=list)
    parameters: list = field(default_factory=list)  # params.Exposed of each expose() call


def preload() -> None:
    """Preload CAD for Linux forks; a fresh interpreter cannot reuse the parent's imports."""
    if USE_FORK:
        import build123d  # noqa: F401


def python_env() -> dict:
    """Environment for a new Python process that must import this same pycodecad."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, (here, os.environ.get("PYTHONPATH")))))


class Run:
    """One script execution in a child process.

    export: also write the shown objects to this path (see files.export), inside the child.
    values: parameter values for expose() ("function.param" or "param" -> value); strict: a value
    no expose() took is an error (the command line), else it is ignored (the window).
    sources: {file: text} of modules the script imports, used instead of the files on disk (the
    window's unsaved edits to a helper module).
    on_done: called from a background thread when the result is ready (e.g. to wake a UI loop).
    The final result, also of a stopped or crashed run, is written to the script's last-run file.
    """

    def __init__(self, code: str, filename: str, export: str | None = None, profile: str = "generic",
                 on_done=None, values: dict | None = None, strict: bool = True, sources: dict | None = None):
        job = dict(code=code, filename=filename, export=export, profile=profile, values=values or {},
                   strict=strict, sources=sources or {})
        self.filename = filename
        self.on_done = on_done
        self.result: Result | None = None
        self.killed = False
        self.reaped = False
        self.lock = threading.Lock()
        self.finished = threading.Event()
        if USE_FORK:
            self.process = None
            read_end, write_end = os.pipe()
            parent = os.getpid()
            with warnings.catch_warnings():  # the app has threads; the child never touches them
                warnings.simplefilter("ignore", DeprecationWarning)
                pid = os.fork()
            if pid == 0:
                status = 1
                try:
                    os.close(read_end)
                    start_child(parent)
                    child_main(job, os.fdopen(write_end, "wb"))
                    status = 0
                except BaseException:
                    traceback.print_exc()
                finally:
                    os._exit(status)
            with contextlib.suppress(OSError):
                os.setpgid(pid, pid)  # also done by the child: whichever runs first
            os.close(write_end)
            self.pid = pid
            stream = os.fdopen(read_end, "rb")
        else:
            code = "from pycodecad.runner import spawned_main; spawned_main()"
            self.process = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, env=python_env())
            assert self.process.stdin is not None and self.process.stdout is not None  # both are PIPE
            self.process.stdin.write(pickle.dumps(job))
            self.process.stdin.close()
            stream = self.process.stdout
        threading.Thread(target=self._finish, args=(stream,), daemon=True).start()

    def _finish(self, stream) -> None:
        try:
            self.result = self._collect(stream)
            if not self.filename.startswith("<"):
                write_last_run(self.filename, self.result)
        except Exception as exc:  # whatever fails (e.g. a folder that is not writable), the run ends
            if self.result is None:
                self.result = Result(error=f"pycodecad could not collect the result: {exc!r}")
        finally:
            self.finished.set()
            if self.on_done:
                self.on_done()

    def _collect(self, stream) -> Result:
        received: list = []
        reader = threading.Thread(target=lambda: received.append(receive(stream)), daemon=True)
        reader.start()  # reads while the child writes: a big result does not fit in the pipe
        code = self._reap()
        reader.join(1.0)  # the result was sent before exiting, or nothing holds the pipe any more
        if self.killed:
            return Result(error="Stopped")
        if not received or received[0] is None:
            how = f"exit code {code}" if code >= 0 else f"killed by {signal.Signals(-code).name}"
            return Result(error=f"The script process died unexpectedly ({how})")
        return received[0]

    def _reap(self) -> int:
        """Wait for the child to exit (without holding the lock: Stop must never block) and
        return its exit code. Anything the script started in its process group is killed."""
        if self.process is not None:
            code = self.process.wait()
            self.reaped = True
            return code
        os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOWAIT)  # exited, not reaped: its pid stays reserved
        with self.lock:
            with contextlib.suppress(OSError):
                os.killpg(self.pid, signal.SIGKILL)
            code = os.waitstatus_to_exitcode(os.waitpid(self.pid, 0)[1])
            self.reaped = True  # from now on the pid may belong to another process
        return code

    def done(self) -> bool:
        return self.finished.is_set()

    def wait(self, timeout: float | None = None) -> Result:
        if not self.finished.wait(timeout):
            raise TimeoutError("The script is still running")
        assert self.result is not None  # _finish always sets it before `finished`
        return self.result

    def kill(self) -> None:
        """Stop the run: kill the child and everything it started."""
        with self.lock:
            if self.reaped:
                return
            self.killed = True
            if self.process is not None:
                self.process.kill()
            else:
                with contextlib.suppress(OSError):
                    os.killpg(self.pid, signal.SIGKILL)


def receive(stream) -> Result | None:
    try:
        return pickle.load(stream)
    except Exception:
        return None
    finally:
        stream.close()


# --- inside the child ----------------------------------------------------------------------

def start_child(parent: int) -> None:
    """First steps of a forked child: its own process group (Stop kills the whole group), death
    with the parent (Linux), no terminal input, and native writes to stdout go to stderr so they
    never mix with what the parent prints (the script's print() output is still captured)."""
    os.setpgid(0, 0)
    if PRCTL is not None:
        PRCTL(1, int(signal.SIGKILL))  # PR_SET_PDEATHSIG
        if os.getppid() != parent:  # the parent died before that
            os._exit(1)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, signal.SIG_DFL)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.dup2(2, 1)


def spawned_main() -> None:
    """Child entry point without fork: the job arrives on stdin, the result leaves on stdout."""
    output = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)  # stray prints from C code must not corrupt the result stream
    child_main(pickle.load(sys.stdin.buffer), output)


def child_main(job: dict, output) -> None:
    result = execute(job["code"], job["filename"], job["values"], job["strict"], job["sources"])
    if job["export"] and result.error is None and result.shown:  # nothing shown: nothing written
        from .files import export

        try:
            result.exported = str(export(result.shown, job["export"], job["profile"]))
        except Exception as exc:
            result.error = f"Export failed: {exc}"
    result.shown = [replace(obj, source=None) for obj in result.shown]  # shapes stay in the child
    pickle.dump(result, output, protocol=pickle.HIGHEST_PROTOCOL)
    output.flush()


def execute(code: str, filename: str, values: dict | None = None, strict: bool = True,
            sources: dict | None = None) -> Result:
    """Run the script in this process (meant for a fresh child) and collect what it shows.
    sources: see Run."""
    from . import api

    start = time.perf_counter()
    sys.dont_write_bytecode = True  # no .pyc of the user's modules: an edit is never masked by a cache
    if not filename.startswith("<"):
        filename = os.path.abspath(filename)
        folder = os.path.dirname(filename)
        os.chdir(folder)
        sys.path.insert(0, folder)
        sys.meta_path.insert(0, ProjectModules(folder, sources or {}))
    elif sources:
        sys.meta_path.insert(0, ProjectModules("", sources))
    for name, text in {filename: code, **(sources or {})}.items():  # tracebacks quote this text, not the disk
        linecache.cache[name] = (len(text), None, text.splitlines(True), name)
    api.scene, api.frames = [], []
    api.values, api.used, api.exposed, api.strict = dict(values or {}), set(), [], strict
    main = types.ModuleType("__main__")  # a real __main__ module, as with `python file.py`: typing and
    main.__file__ = filename              # dataclass tools look classes' names up in sys.modules
    sys.modules["__main__"] = main        # (this child process runs only this script)
    namespace = main.__dict__
    output = CappedOutput()
    result = Result(warnings=absolute_path_warnings(code))
    try:
        with contextlib.redirect_stdout(output):
            try:
                exec(compile(code, filename, "exec"), namespace)
            except SystemExit as exc:
                if exc.code not in (None, 0):  # sys.exit() and sys.exit(0) are a normal end
                    raise
        result.shown = list(api.scene)
        result.frames = list(api.frames)
        unknown = sorted(set(api.values) - api.used)
        if strict and unknown:
            raise ValueError(f"No exposed parameter {', '.join(unknown)} (see expose() in the script)")
        if not result.shown and not result.frames:
            result.warnings.append(NOTHING_SHOWN)
    except BaseException as exc:  # user code may raise anything, SystemExit included
        describe_error(result, exc, filename)
    result.parameters = list(api.exposed)
    result.stdout = output.text()
    result.duration = time.perf_counter() - start
    return result


class ProjectModules:
    """An import hook for the modules of the script's folder (and its subfolders): read from their
    source, never from an old .pyc; the ones in sources ({file: text}) from that text. Every other
    module as usual."""

    def __init__(self, folder: str, sources: dict) -> None:
        self.folder, self.sources = folder, sources

    def find_spec(self, name, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
            return None
        if spec.origin not in self.sources and not self.in_project(spec.origin):
            return None
        loader = ProjectSource(name, spec.origin, self.sources.get(spec.origin))
        return importlib.util.spec_from_file_location(name, spec.origin, loader=loader,
                                                      submodule_search_locations=spec.submodule_search_locations)

    def in_project(self, origin: str) -> bool:
        """In the script's folder or its subfolders, but not in an environment's installed packages."""
        origin = os.path.normcase(origin)
        folder = os.path.normcase(os.path.join(self.folder, ""))
        return bool(self.folder) and origin.startswith(folder) and "site-packages" not in origin


class ProjectSource(importlib.machinery.SourceFileLoader):
    """A module file read from its source, or from a text in memory (tracebacks show that text too)."""

    def __init__(self, name: str, path: str, text: str | None) -> None:
        super().__init__(name, path)
        self.text = text

    def get_data(self, path: str) -> bytes:
        return self.text.encode("utf-8") if path == self.path and self.text is not None else super().get_data(path)

    def path_stats(self, path: str):
        raise OSError("no bytecode")  # a .pyc can be stale within the same second and size: never used


def describe_error(result: Result, exc: BaseException, filename: str) -> None:
    """The traceback of the user's own files (the script and modules in its folder), and the
    innermost place in them where it failed. Library frames between them are left out."""
    folder = os.path.dirname(filename) + os.sep

    def user_file(path: str | None) -> bool:
        return bool(path) and (path == filename or path.startswith(folder) and not filename.startswith("<")
                                and "site-packages" not in path)

    frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if user_file(frame.filename)]
    if isinstance(exc, SyntaxError) and user_file(exc.filename):
        result.error_file, result.error_line = exc.filename, exc.lineno
    elif frames:
        result.error_file, result.error_line = frames[-1].filename, frames[-1].lineno
    head = "Traceback (most recent call last):\n" if frames else ""
    text = head + "".join(traceback.format_list(frames)) + "".join(traceback.format_exception_only(exc))
    result.error = text.rstrip()


def absolute_path_warnings(code: str) -> list[str]:
    """Absolute paths into the home folder make a part work only on this PC."""
    home = re.escape(os.path.expanduser("~"))
    found = sorted(set(re.findall(rf"""['"]({home}[/\\][^'"]*)['"]""", code)))
    return [f"Absolute path {path!r}: use a path relative to the script folder so the part works on any PC"
            for path in found]


def report(script: str, result: Result) -> dict:
    """The result as plain JSON data (what `pycodecad check` prints and last-run files hold)."""
    from . import __version__

    objects = []
    for obj in result.shown[:1000]:
        bbox = obj.bbox()
        objects.append(dict(name=obj.name[:200], color=hex_color(obj.color),
                            volume=obj.volume, bbox=dict(min=bbox[0], max=bbox[1]) if bbox else None))
    where = f"{result.error_file}:{result.error_line}" if result.error_file else None
    summary = "".join((result.error or "").splitlines()[-1:])
    summary = summary if len(summary) <= 2000 else summary[:2000] + " ... (truncated)"
    return dict(ok=result.error is None, file=script, error=summary or None, where=where,
                traceback=tail(result.error, 20000, "traceback"), stdout=tail(result.stdout, 4000, "output"),
                warnings=[warning[:1000] for warning in result.warnings[:20]],
                objects=objects, objects_total=len(result.shown), frames=len(result.frames),
                parameters=to_json(result.parameters),
                duration=round(result.duration, 3),
                time=datetime.datetime.now().isoformat(timespec="seconds"), pycodecad=__version__)


def tail(text: str | None, limit: int, what: str) -> str | None:
    """The end of a long text, marked as cut."""
    if text is None or len(text) <= limit:
        return text
    return f"... ({what} truncated)\n" + text[-limit:]


def write_last_run(script: str, result: Result) -> None:
    from .sidecar import write_json

    write_json(script, "last-run", report(script, result))


class CappedOutput(io.StringIO):
    """stdout replacement that keeps only the last STDOUT_LIMIT characters."""

    truncated = False

    def write(self, text: str) -> int:
        super().write(text)
        if self.tell() > 2 * STDOUT_LIMIT:
            tail = self.getvalue()[-STDOUT_LIMIT:]
            self.seek(0)
            self.truncate()
            super().write(tail)
            self.truncated = True
        return len(text)

    def text(self) -> str:
        value = self.getvalue()
        if self.truncated or len(value) > STDOUT_LIMIT:
            return "... (output truncated)\n" + value[-STDOUT_LIMIT:]
        return value
