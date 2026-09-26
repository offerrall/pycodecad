import json
import os
import py_compile
import sys
import time
from pathlib import Path

import pytest

from conftest import start_endless, tetrahedron
from pycodecad import runner

BOX = "from build123d import Box\nfrom pycodecad import show\nshow(Box(10, 20, 30), name='box', color='red')\n"


def run(code, filename="<editor>"):
    return runner.Run(code, str(filename)).wait(60)


def test_shows_objects_with_mesh_and_volume():
    result = run(BOX)
    assert result.error is None
    [box] = result.shown
    assert (box.name, box.color, box.source) == ("box", (1.0, 0.0, 0.0), None)
    assert box.volume == pytest.approx(6000)
    assert box.mesh.bbox() == ((-5, -10, -15), (5, 10, 15))


def test_error_and_line(tmp_path):
    script = str(tmp_path / "part.py")
    result = run("x = 1\n\nraise ValueError('bad size')\n", script)
    assert (result.error or "").endswith("ValueError: bad size")
    assert (result.error_file, result.error_line) == (script, 3) and result.shown == []
    assert run("def f(:\n", script).error_line == 1


def test_errors_point_at_the_users_file_and_last_run_is_written(tmp_path):
    import json

    script = tmp_path / "part.py"
    (tmp_path / "helper.py").write_text("def make():\n    return 1 / 0\n")
    result = run("import helper\nhelper.make()\n", script)
    assert (result.error_file, result.error_line) == (str(tmp_path / "helper.py"), 2)
    error = result.error or ""
    assert "runner.py" not in error and error.endswith("ZeroDivisionError: division by zero")
    saved = json.loads((tmp_path / ".pycodecad" / "part.py.last-run.json").read_text())
    assert not saved["ok"] and saved["where"] == f"{tmp_path / 'helper.py'}:2"

    result = run("from build123d import import_svg\n\nimport_svg('missing.svg')\n", script)
    assert (result.error_file, result.error_line) == (str(script), 3)
    error = result.error or ""
    assert "FileNotFoundError" in error or "missing.svg" in error
    assert "site-packages" not in error  # library frames are left out

    run(BOX, script)
    saved = json.loads((tmp_path / ".pycodecad" / "part.py.last-run.json").read_text())
    assert saved["ok"] and saved["objects"][0]["name"] == "box" and saved["pycodecad"]


def test_absolute_home_paths_are_warned_about():
    import os

    home = os.path.expanduser("~")
    result = run(f"path = '{home}/models/logo.svg'\n")
    assert result.error is None and "relative to the script folder" in result.warnings[0]


def test_stop_kills_any_script():
    started = time.monotonic()
    child = runner.Run("import time\nwhile True:\n    time.sleep(1)\n", "<editor>")
    time.sleep(0.2)
    child.kill()
    assert child.wait(5).error == "Stopped"
    assert time.monotonic() - started < 5
    child.kill()  # already gone: harmless


def test_script_folder_is_cwd_and_import_path_and_helpers_are_fresh(tmp_path):
    script = tmp_path / "main.py"
    (tmp_path / "data.txt").write_text("from a file")
    code = "import helper\nprint(open('data.txt').read(), helper.VALUE)\n"
    (tmp_path / "helper.py").write_text("VALUE = 1\n")
    assert run(code, script).stdout == "from a file 1\n"
    (tmp_path / "helper.py").write_text("VALUE = 2\n")
    assert run(code, script).stdout == "from a file 2\n"


@pytest.mark.parametrize("relative, module", [
    ("helper.py", "helper"),
    ("helpers/__init__.py", "helpers"),
    ("helpers/sizes.py", "helpers.sizes"),
])
def test_project_imports_ignore_existing_bytecode_after_a_same_second_edit(tmp_path, relative, module):
    helper = tmp_path / relative
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("SIZE = 10\n", encoding="utf-8")
    stamp = 1_700_000_000_100_000_000
    os.utime(helper, ns=(stamp, stamp))
    cached = py_compile.compile(str(helper), doraise=True,
                                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
    assert cached is not None
    bytecode = Path(cached).read_bytes()
    helper.write_text("SIZE = 20\n", encoding="utf-8")
    os.utime(helper, ns=(stamp + 100_000_000, stamp + 100_000_000))

    result = run(f"import {module}\nprint({module}.SIZE)\n", tmp_path / "main.py")
    assert result.error is None, result.error
    assert result.stdout == "20\n"
    assert Path(cached).read_bytes() == bytecode  # the user's existing cache is left alone


def test_stdout_is_capped():
    result = run(f"print('x' * {3 * runner.STDOUT_LIMIT})\nprint('end')")
    assert result.stdout.startswith("... (output truncated)")
    assert result.stdout.endswith("end\n") and len(result.stdout) < runner.STDOUT_LIMIT + 100


def test_without_show_nothing_is_shown():
    result = run("from build123d import *\nbox = Box(1, 1, 1)\n")
    assert result.error is None and result.shown == [] and result.warnings == ["Nothing shown: call show(...)"]
    assert run("from build123d import *\nfrom pycodecad import clear, show\nshow(Box(1, 1, 1))\nclear()\n").shown == []
    assert run(BOX).warnings == []


def test_crash_is_reported():
    assert "died unexpectedly (exit code 3)" in (run("import os\nos._exit(3)\n").error or "")


def test_fallback_without_fork(monkeypatch):
    monkeypatch.setattr(runner, "USE_FORK", False)
    result = run(BOX)
    assert result.error is None and [obj.name for obj in result.shown] == ["box"]


def test_spawned_run_keeps_paths_unsaved_helpers_parameters_and_export(tmp_path, monkeypatch):
    from pycodecad.files import read_triangles

    monkeypatch.setattr(runner, "USE_FORK", False)
    folder = tmp_path / "pièces with spaces"
    folder.mkdir()
    helper = folder / "helper.py"
    helper.write_text("SIZE = 1\n", encoding="utf-8")
    script = folder / "part.py"
    target = folder / "pièce.stl"
    code = ("from build123d import Box\nfrom helper import SIZE\nfrom pycodecad import expose, show\n"
            "def part(scale: float = 1.0):\n    return Box(SIZE * scale, 2, 3)\n"
            "print('pièce')\nshow(expose(part))\n")
    child = runner.Run(code, str(script), sources={str(helper): "SIZE = 13\n"},
                       values={"part.scale": 2.0}, export=str(target))
    result = child.wait(60)
    assert result.error is None, result.error
    assert result.stdout == "pièce\n" and result.exported == str(target)
    assert result.shown[0].bbox() == ((-13, -1, -1.5), (13, 1, 1.5))
    assert result.parameters[0].params[0].value == 2.0
    points = read_triangles(target)
    assert points.min(axis=0).tolist() == [-13, -1, -1.5]
    assert points.max(axis=0).tolist() == [13, 1, 1.5]
    assert helper.read_text() == "SIZE = 1\n"

    edited = "raise ValueError('unsaved helper')\n"
    result = runner.Run(code, str(script), sources={str(helper): edited}).wait(60)
    assert (result.error_file, result.error_line) == (str(helper), 1)
    assert edited.strip() in (result.error or "")


@pytest.mark.parametrize("folder, origin, expected", [
    ("C:\\", "C:\\helper.py", True),
    ("C:\\Models", "c:/models/helper.py", True),
    ("C:\\Models", "C:\\Models2\\helper.py", False),
    ("C:\\Models", "C:\\Models\\venv\\Lib\\site-packages\\helper.py", False),
    ("C:\\Models", "D:\\Models\\helper.py", False),
])
def test_project_import_boundaries_on_windows(monkeypatch, folder, origin, expected):
    import ntpath
    from types import SimpleNamespace

    monkeypatch.setattr(runner, "os", SimpleNamespace(path=ntpath))
    assert runner.ProjectModules(folder, {}).in_project(origin) is expected


def test_public_api_is_show_clear_import_mesh_and_expose():
    import pycodecad

    assert pycodecad.__all__ == ["show", "clear", "frame", "import_mesh", "expose"]
    for name in ("show", "clear", "frame", "import_mesh", "expose"):
        assert callable(getattr(pycodecad, name))
    for name in ("render", "Mesh"):
        with pytest.raises(AttributeError):
            getattr(pycodecad, name)


def test_show_outside_pycodecad_does_nothing():
    from build123d import Box
    from pycodecad import clear, show

    show(Box(1, 1, 1))
    clear()


def test_fillet_in_a_helper_module(tmp_path):
    (tmp_path / "parts.py").write_text(
        "from build123d import Align, Axis, Box, fillet\n"
        "def box(width=120):\n"
        "    return fillet(Box(width, 80, 45, align=(Align.CENTER, Align.CENTER, Align.MIN)).edges().filter_by(Axis.Z), 6)\n")
    result = run("import parts\nfrom pycodecad import show\nshow(parts.box())\n", tmp_path / "main.py")
    assert result.error is None and result.shown[0].volume == pytest.approx(120 * 80 * 45 - 4 * 36 * 45 * (1 - 3.14159265 / 4), rel=1e-4)
    result = run("import parts\nparts.box(10)\n", tmp_path / "main.py")  # 2 x 6 mm fillets cannot fit in 10 mm
    assert "Failed creating a fillet" in (result.error or "") and result.error_file == str(tmp_path / "parts.py")


def last_run(folder):
    return json.loads((folder / ".pycodecad" / "part.py.last-run.json").read_text())


def test_last_run_holds_the_final_result_of_crashes_and_stops(tmp_path):
    script = tmp_path / "part.py"
    run(BOX, script)
    assert last_run(tmp_path)["ok"]
    assert "exit code 3" in (run("import os\nos._exit(3)\n", script).error or "")
    assert "exit code 3" in last_run(tmp_path)["error"]
    if sys.platform != "win32":
        assert "killed by SIGKILL" in (run("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", script).error or "")
    child = runner.Run("import time\ntime.sleep(60)\n", str(script))
    time.sleep(0.2)
    child.kill()
    assert child.wait(5).error == "Stopped" and last_run(tmp_path)["error"] == "Stopped"


def test_sys_exit_zero_is_success_and_meshes_are_shown(tmp_path):
    assert run("import sys\nsys.exit()\n").error is None
    assert run(BOX + "import sys\nsys.exit(0)\n").shown[0].name == "box"
    assert (run("import sys\nsys.exit(2)\n").error or "").endswith("SystemExit: 2")
    from pycodecad.files import write_stl

    write_stl([tetrahedron()], tmp_path / "t.stl")
    result = run("from pycodecad import import_mesh, show\nshow(import_mesh('t.stl'), name='reference')\n",
                 tmp_path / "part.py")
    assert [obj.name for obj in result.shown] == ["reference"]


def test_error_summary_is_bounded(tmp_path):
    run("print('y' * 10000)\nraise ValueError('x' * 100000)", tmp_path / "part.py")
    saved = last_run(tmp_path)
    assert len(saved["error"]) < 2100 and saved["stdout"].startswith("... (output truncated)")


@pytest.mark.skipif(not runner.USE_FORK, reason="Linux process-group cleanup")
def test_stop_kills_what_the_script_started_and_never_hangs():
    # A grandchild keeps the result pipe open: the run still ends at once, with nothing left behind.
    code = "import subprocess, time\nsubprocess.Popen(['sleep', '60'])\ntime.sleep(60)\n"
    child = runner.Run(code, "<editor>")
    time.sleep(0.5)
    group = child.pid
    child.kill()
    assert child.wait(5).error == "Stopped"
    with pytest.raises(ProcessLookupError):
        os.killpg(group, 0)
    finished = runner.Run("import subprocess\nsubprocess.Popen(['sleep', '60'])\n", "<editor>")
    assert finished.wait(5).error is None


def test_stop_does_not_block_without_fork(monkeypatch):
    monkeypatch.setattr(runner, "USE_FORK", False)
    child = runner.Run("import threading, time\nthreading.Thread(target=time.sleep, args=(60,)).start()\n",
                       "<editor>")
    time.sleep(1.0)
    started = time.monotonic()
    child.kill()
    assert time.monotonic() - started < 1 and child.wait(5).error == "Stopped"


@pytest.mark.skipif(not runner.USE_FORK, reason="Linux parent-death signal and /proc")
def test_killing_the_parent_leaves_no_orphan(tmp_path):
    # The CLI is killed (SIGKILL: no cleanup at all); its script child dies with it.
    parent, child = start_endless(tmp_path, "check")
    parent.kill()
    parent.wait()
    deadline = time.monotonic() + 5
    while alive(child):
        assert time.monotonic() < deadline, "the script outlived its parent"
        time.sleep(0.05)


def alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_a_run_always_ends_even_when_reporting_fails(tmp_path, monkeypatch):
    result = run("from pathlib import Path\n" + BOX.replace("name='box'", "name=Path('box')"), tmp_path / "part.py")
    assert "name must be a string" in (result.error or "")

    def broken(script, result):
        raise TypeError("cannot report")

    monkeypatch.setattr(runner, "write_last_run", broken)
    result = run(BOX, tmp_path / "part.py")  # the report fails; the run still ends with its result
    assert result.error is None and result.shown[0].name == "box"


def test_sources_replace_a_helper_module_on_disk(tmp_path):
    helper = tmp_path / "helper.py"
    helper.write_text("SIZE = 10\n")
    import importlib.util
    import py_compile

    py_compile.compile(str(helper), cfile=importlib.util.cache_from_source(str(helper)))  # a stale .pyc is ignored
    script = str(tmp_path / "part.py")
    code = "import helper\nprint(helper.SIZE)\n"
    assert runner.Run(code, script).wait(60).stdout == "10\n"
    edited = {str(helper): "SIZE = 20\n"}
    assert runner.Run(code, script, sources=edited).wait(60).stdout == "20\n"
    result = runner.Run(code, script, sources={str(helper): "SIZE = 1\n\nraise ValueError('edited')\n"}).wait(60)
    assert (result.error_file, result.error_line) == (str(helper), 3)
    assert "raise ValueError('edited')" in (result.error or "")  # the traceback shows the edited text
    assert helper.read_text() == "SIZE = 10\n"


def test_classes_of_the_script_resolve_their_type_names(tmp_path):
    # typing.get_type_hints (dataclasses, pytypehint @immutable) looks names up in sys.modules["__main__"]
    script = tmp_path / "part.py"
    script.write_text("from typing import Annotated, get_type_hints\nfrom dataclasses import dataclass\n"
                      "Size = Annotated[float, 'mm']\n@dataclass\nclass Part:\n    size: 'Size'\n"
                      "print(get_type_hints(Part)['size'] is float)\n")
    result = runner.Run(script.read_text(), str(script)).wait(60)
    assert result.error is None and result.stdout.strip() == "True"
