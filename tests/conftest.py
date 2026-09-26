"""Shared helpers. Tests write files only under pytest's tmp_path."""
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from pycodecad import cad, runner

PART = "from build123d import Box\nfrom pycodecad import show\nshow(Box(40, 30, 10), name='plate')\n"
ENDLESS = "import os, time\nopen('pid', 'w').write(str(os.getpid()))\nwhile True:\n    time.sleep(0.1)\n"


def gl_available() -> bool:
    try:
        import moderngl

        moderngl.create_standalone_context().release()
        return True
    except Exception:
        return False


needs_gl = pytest.mark.skipif(not gl_available(), reason="no off-screen OpenGL")
needs_display = pytest.mark.skipif(sys.platform not in ("win32", "darwin")
                                   and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
                                   reason="no display for a (hidden) window")


@pytest.fixture(scope="session", autouse=True)
def preloaded():
    runner.preload()  # like the window: forked runs start with build123d already imported


@pytest.fixture(autouse=True)
def temporary_cache(tmp_path, monkeypatch):
    """pycodecad's temporary folder (~/.cache/pycodecad/tmp) goes under tmp_path, also for subprocesses."""
    monkeypatch.setattr(cad, "TEMP", tmp_path / "cache" / "pycodecad" / "tmp")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def tetrahedron() -> cad.Mesh:
    a, b, c, d = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float32)
    points = np.array([a, c, b, a, b, d, a, d, c, b, c, d]).reshape(-1, 3)
    return cad.Mesh(points, np.zeros_like(points), np.empty((0, 3)))


def start_endless(folder, *arguments, **options) -> tuple[subprocess.Popen, int]:
    """`pycodecad <arguments> part.py` on a script that never ends. Returns the pycodecad process and
    the pid of the script's process, once it runs."""
    script = folder / "part.py"
    script.write_text(ENDLESS)
    command = subprocess.Popen([sys.executable, "-m", "pycodecad", *arguments, str(script)], env=runner.python_env(),
                               **options)
    deadline = time.monotonic() + 30
    while not (folder / "pid").exists() or not (folder / "pid").read_text():
        assert time.monotonic() < deadline, "the script did not start"
        time.sleep(0.05)
    return command, int((folder / "pid").read_text())
