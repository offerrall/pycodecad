"""Command line: open the window, or check/render/export a script without it.

    pycodecad file.py [--read-only] [--no-run]           window on the file's folder, file.py runs (created if missing)
    pycodecad folder/                                    window on a folder (its part runs: see workspace.find_main)
    pycodecad examples [folder]                          copy the examples there once (default ./pycodecad-examples), open it
    pycodecad check file.py                              run it, print the result as JSON
    pycodecad render file.py out.png [--views iso | iso,front,top | window] [--size 800x600] [--frame N]
    pycodecad export file.py out.stl [--profile bambu]   also .3mf .step .glb .brep
    pycodecad context file.py                            print the AI context

check, render and export take --set KEY=VALUE (repeatable) for the parameters of expose():
KEY is "param" or "function.param".

Ctrl+C (or SIGTERM/SIGHUP) stops the running script and exits with code 130.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import sys
from pathlib import Path

from . import __version__

COMMANDS = ("check", "render", "export", "context")


class Usage(Exception):
    """A command line that cannot work: the message is printed and pycodecad exits with 1."""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):  # a console that is not UTF-8 (Windows): never fail to print
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")  # pyright: ignore[reportAttributeAccessIssue]
    stops = [number for number in (signal.SIGTERM, getattr(signal, "SIGHUP", None)) if number is not None]
    previous = {number: signal.signal(number, interrupt) for number in stops}
    try:
        from .cad import remove_stale_temp

        remove_stale_temp()
        if argv and argv[0] in COMMANDS:
            return command(argv[0], argv[1:])
        if argv and argv[0] == "examples":
            return examples(argv[1:])
        return window(argv)
    except KeyboardInterrupt:  # the run (if any) is already killed
        print("pycodecad: interrupted", file=sys.stderr)
        return 130
    except (OSError, Usage) as exc:
        from .sidecar import error_text

        print(f"pycodecad: {error_text(exc) if isinstance(exc, OSError) else exc}", file=sys.stderr)
        return 1
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def interrupt(number, frame) -> None:
    raise KeyboardInterrupt


def window(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pycodecad", description="Code-CAD window for build123d scripts. "
                                     "Other commands: pycodecad {check,render,export,context,examples} --help")
    parser.add_argument("file", help="script to run (created if it does not exist), or a folder")
    parser.add_argument("--read-only", action="store_true", help="an order form: parameters, Run and Export, no "
                        "code; scripts are never written")
    parser.add_argument("--no-run", action="store_true", help="do not run the script when the window opens")
    parser.add_argument("--screenshot", metavar="PNG", help="save a picture of the window after the first run and quit")
    parser.add_argument("--version", action="version", version=f"pycodecad {__version__}")
    options = parser.parse_args(argv)
    from .app import open_window

    open_window(options.file, screenshot=options.screenshot, read_only=options.read_only, run=not options.no_run)
    return 0


def examples(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pycodecad examples", description="Copy the examples into a folder the "
                                     "first time, then open the window on it (an existing folder is opened as it is).")
    parser.add_argument("folder", nargs="?", default="pycodecad-examples", help="default ./pycodecad-examples")
    parser.add_argument("--no-run", action="store_true", help="do not run the script when the window opens")
    options = parser.parse_args(argv)
    target = Path(options.folder)
    if not target.exists():
        shutil.copytree(bundled_examples(), target, ignore=shutil.ignore_patterns("__pycache__", ".pycodecad"))
        print(f"Copied the examples to {target.resolve()}")
    from .app import open_window

    open_window(str(target), run=not options.no_run)
    return 0


def bundled_examples() -> Path:
    """The examples inside the installed package, or next to the sources in a checkout."""
    for folder in (Path(__file__).parent / "examples", Path(__file__).parents[2] / "examples"):
        if folder.is_dir():
            return folder
    raise Usage("the examples are not installed with this copy of pycodecad")


def command(name: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"pycodecad {name}", allow_abbrev=False)
    parser.add_argument("file", help="the script")
    if name == "render":
        parser.add_argument("output", help="PNG file to write")
        parser.add_argument("--views", default="iso", help="iso (default), front, back, left, right, top or "
                            "bottom; several make a labeled grid (iso,front,top,right); window is the camera of "
                            "the open window")
        parser.add_argument("--size", help="WIDTHxHEIGHT of each view (default 800x600, or the window's)")
        parser.add_argument("--frame", type=int, metavar="N", help="frame N (1, 2, ...) of an animation made "
                            "with frame(); by default the scene at the end of the script")
    if name == "export":
        parser.add_argument("output", help="file to write: .stl .3mf .step .glb or .brep")
        from .files import PROFILES

        parser.add_argument("--profile", choices=PROFILES, help="3MF flavor (default generic)")
    if name != "context":
        parser.add_argument("--set", action="append", default=[], type=setting, metavar="KEY=VALUE",
                            help="value of an exposed parameter (\"param\" or \"function.param\"); repeatable")
    options = parser.parse_args(argv)
    script = Path(options.file).resolve()
    from .sidecar import read_script

    picture = render_plan(script, options) if name == "render" else None
    if name == "export":
        check_export(options)
    code = read_script(script)
    from . import runner

    export = str(Path(options.output).resolve()) if name == "export" else None
    values = dict(getattr(options, "set", []))
    run = runner.Run(code, str(script), export=export, profile=getattr(options, "profile", None) or "generic",
                     values=values)
    try:
        result = run.wait()
    except KeyboardInterrupt:
        run.kill()
        with contextlib.suppress(TimeoutError):
            run.wait(5)  # its last-run file says "Stopped"
        raise
    if name == "check":
        print(json.dumps(runner.report(str(script), result), indent=2))
        return 1 if result.error else 0
    if name == "context":
        from .context import ai_context

        print(ai_context(script, result))
        return 0
    if result.stdout and name == "export":
        print(result.stdout, end="")
    if result.error:
        print(result.error, file=sys.stderr)
        return 1
    frame = getattr(options, "frame", None)
    if frame is not None and not 1 <= frame <= len(result.frames):
        raise Usage(f"--frame {frame}: the script made {len(result.frames)} frames (frame() calls)")
    if not result.shown and not frame:
        raise Usage("nothing shown: call show() in the script")
    if name == "export":
        print(f"Wrote {result.exported}")
        return 0
    assert picture is not None  # name == "render": planned before running
    return render(result.frames[frame - 1] if frame else result.shown, options.output, *picture)


def setting(text: str) -> tuple[str, str]:
    """--set KEY=VALUE: the value stays a string, converted by expose() to the parameter's type."""
    key, equals, value = text.partition("=")
    if not equals or not key.strip():
        raise argparse.ArgumentTypeError(f"must look like KEY=VALUE (width=80 or box.width=80), not {text!r}")
    return key.strip(), value


def check_output(output: str) -> None:
    folder = Path(output).resolve().parent
    if not folder.is_dir():
        raise Usage(f"the folder of {output} does not exist: {folder}")


def check_export(options) -> None:
    from .files import FORMATS

    kind = Path(options.output).suffix.lower().lstrip(".")
    if kind not in FORMATS:
        raise Usage(f"cannot export {options.output}: use one of .{', .'.join(FORMATS)}")
    if options.profile and kind != "3mf":
        raise Usage("--profile is only for .3mf files")
    check_output(options.output)


def render_plan(script: Path, options) -> tuple[list, tuple[int, int]]:
    """The views (names or the window's Camera) and the size of each, checked before running."""
    from .camera import check_view
    from .renderer import check_size
    from .sidecar import load_camera

    if Path(options.output).suffix.lower() != ".png":
        raise Usage(f"render writes PNG pictures: {options.output} must end in .png")
    check_output(options.output)
    size = (800, 600)
    if options.size:
        try:
            width, height = (int(value) for value in options.size.lower().split("x"))
            size = (width, height)
            check_size(size)
        except ValueError:
            raise Usage(f"--size must look like 800x600 (1 to 8192 pixels per side), not {options.size}") from None
    views: list = options.views.split(",")
    for view in views:
        try:
            check_view(view, "window")
        except ValueError as exc:
            raise Usage(str(exc)) from None
    if "window" in views:
        if len(views) > 1:
            raise Usage("--views window shows the window camera alone: do not combine it with other views")
        try:
            camera, window_size = load_camera(script)
        except (OSError, ValueError):
            raise Usage(f"no window camera saved for {script.name} yet: open it with "
                        f"`pycodecad {script.name}` and move the view") from None
        views = [camera]
        if options.size is None:
            size = window_size
    return views, size


def render(shown: list, output: str, views: list, size: tuple[int, int]) -> int:
    from .renderer import png_bytes, render_views

    Path(output).write_bytes(png_bytes(render_views(shown, views, size)))
    print(f"Wrote {Path(output).resolve()}")
    return 0
