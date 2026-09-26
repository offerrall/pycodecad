"""Script files: reading them, writing them safely (atomically), and what pycodecad keeps next to them.

    <folder>/.pycodecad/<file>.last-run.json   result of the last run (the JSON of `pycodecad check`)
    <folder>/.pycodecad/<file>.camera.json     camera of the window, for `pycodecad render --views window`
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .camera import Camera, wrap_yaw

UMASK = os.umask(0o022)
os.umask(UMASK)


def read_script(path: str | Path) -> str:
    """The text of a script. Raises OSError, also for a file that is not UTF-8 text."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise OSError(f"{path}: not a UTF-8 text file") from None


def error_text(exc: OSError) -> str:
    """A short message for a failed file operation: "path: reason"."""
    return f"{exc.filename}: {exc.strerror}" if exc.filename and exc.strerror else str(exc)


def sidecar(script: str | Path, kind: str) -> Path:
    """kind: "last-run" or "camera"."""
    script = Path(script)
    return script.parent / ".pycodecad" / f"{script.name}.{kind}.json"


def write_atomic(path: str | Path, text: str) -> int:
    """Replace the file in one step (readers see the old or the new text, never a part), keeping
    its permissions. Returns the modification time (ns) of what was written."""
    path = Path(path)
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o666 & ~UMASK
    try:
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".pycodecad-tmp", dir=path.parent)
    except OSError as exc:
        exc.filename = str(path)  # report the file asked for, not the temporary one
        raise
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        written = os.stat(temporary).st_mtime_ns
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return written


def write_json(script: str | Path, kind: str, data: dict) -> None:
    target = sidecar(script, kind)
    target.parent.mkdir(exist_ok=True)
    write_atomic(target, json.dumps(data, indent=2))


def save_camera(script: str | Path, camera: Camera, size: tuple[int, int]) -> None:
    write_json(script, "camera", asdict(camera) | dict(width=size[0], height=size[1]))


def load_camera(script: str | Path) -> tuple[Camera, tuple[int, int]]:
    """The window's camera and view size. Raises OSError or ValueError when there is none."""
    text = sidecar(script, "camera").read_text(encoding="utf-8")
    try:
        saved = json.loads(text)
        x, y, z = saved["target"]
        camera = Camera(target=(float(x), float(y), float(z)), distance=float(saved["distance"]),
                        yaw=wrap_yaw(saved["yaw"]), pitch=float(saved["pitch"]), fov=float(saved["fov"]))
        return camera, (int(saved["width"]), int(saved["height"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid camera file: {exc}") from None
