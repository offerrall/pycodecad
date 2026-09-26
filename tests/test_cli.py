import json
import os
import signal
import struct
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest

from conftest import PART, needs_gl, start_endless, tetrahedron
from pycodecad.cli import main
from pycodecad.runner import python_env


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack("!II", data[16:24])


def test_check_prints_objects_and_errors(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(PART)
    assert main(["check", str(script)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["objects"][0]["name"] == "plate"
    assert report["objects"][0]["bbox"] == {"min": [-20, -15, -5], "max": [20, 15, 5]}
    script.write_text("from build123d import Box\n\nBox(1, 2)\n")
    assert main(["check", str(script)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["where"] == f"{script}:3" and "TypeError" in report["error"] and not report["ok"]


def test_empty_scene_is_a_warning_in_check_and_an_error_in_render_and_export(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text("from build123d import Box\n\nbox = Box(1, 2, 3)\n")
    assert main(["check", str(script)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["objects"] == [] and report["warnings"] == ["Nothing shown: call show(...)"]
    for args in (["render", str(script), str(tmp_path / "out.png")], ["export", str(script), str(tmp_path / "out.stl")]):
        assert main(args) == 1
        assert capsys.readouterr().err == "pycodecad: nothing shown: call show() in the script\n"
    assert not (tmp_path / "out.png").exists() and not (tmp_path / "out.stl").exists()


def test_export(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(PART)
    assert main(["export", str(script), str(tmp_path / "part.3mf"), "--profile", "bambu"]) == 0
    assert (tmp_path / "part.3mf").stat().st_size > 0
    assert "Wrote" in capsys.readouterr().out


@needs_gl
def test_render_views_and_window_camera(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(PART)
    assert main(["render", str(script), str(tmp_path / "one.png"), "--size", "320x200"]) == 0
    assert png_size(tmp_path / "one.png") == (320, 200)
    assert main(["render", str(script), str(tmp_path / "front.png"), "--views", "front", "--size", "100x80"]) == 0
    assert png_size(tmp_path / "front.png") == (100, 80)
    assert main(["render", str(script), str(tmp_path / "grid.png"), "--views", "iso,front,top", "--size", "100x80"]) == 0
    assert png_size(tmp_path / "grid.png") == (200, 160)
    assert main(["render", str(script), str(tmp_path / "w.png"), "--views", "window"]) == 1
    assert "no window camera" in capsys.readouterr().err
    (tmp_path / ".pycodecad").mkdir(exist_ok=True)
    (tmp_path / ".pycodecad" / "part.py.camera.json").write_text(json.dumps(
        dict(target=[0, 0, 0], distance=90, yaw=10, pitch=20, fov=45, width=300, height=150)))
    assert main(["render", str(script), str(tmp_path / "w.png"), "--views", "window"]) == 0
    assert png_size(tmp_path / "w.png") == (300, 150)


@needs_gl
def test_render_keeps_translated_rotated_instances_in_place():
    from pycodecad.cad import Shown
    from pycodecad.renderer import render_views

    mesh = tetrahedron()
    placed = Shown("placed", (0.2, 0.8, 0.3), mesh,
                   matrix=(0, -1, 0, 30, 1, 0, 0, -20, 0, 0, 1, 40, 0, 0, 0, 1))
    scene = [Shown("base", (0.8, 0.3, 0.2), mesh), placed]
    # Bake the transformed coordinates independently of the renderer's placement matrices.
    baked = [replace(obj, mesh=obj.world(), matrix=None) for obj in scene]
    actual = render_views(scene, ["iso", "front", "top"], (160, 120))
    expected = render_views(baked, ["iso", "front", "top"], (160, 120))
    assert np.array_equal(actual, expected)


def test_context_lists_folder_state_and_commands(tmp_path, capsys):
    from pycodecad.context import quote

    script = tmp_path / "part.py"
    script.write_text(PART)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.svg").write_text("<svg/>")
    assert main(["context", str(script)]) == 0
    text = capsys.readouterr().out
    for expected in (f"Folder: {tmp_path}", "assets/logo.svg (6 B)", "plate: size 40 x 30 x 10 mm",
                     f"check {quote('part.py')}", "--views window", "import_mesh(path"):
        assert expected in text


@needs_gl
def test_many_runs_leave_bounded_files(tmp_path, capsys):
    from pycodecad import cad

    script = tmp_path / "part.py"
    script.write_text(PART + "from pycodecad import import_mesh\n"
                      "import_mesh('tetra.stl', solid=True)\n")
    from pycodecad.files import write_stl

    write_stl([tetrahedron()], tmp_path / "tetra.stl")
    for _ in range(5):
        assert main(["check", str(script)]) == 0
        assert main(["render", str(script), str(tmp_path / "out.png"), "--size", "64x48"]) == 0
    capsys.readouterr()
    assert [p.name for p in (tmp_path / ".pycodecad").iterdir()] == ["part.py.last-run.json"]
    assert (tmp_path / ".pycodecad" / "part.py.last-run.json").stat().st_size < 1_000_000
    assert list(cad.TEMP.iterdir()) == []


def test_check_stdout_stays_json_with_native_writes(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("import os\nos.write(1, b'native output\\n')\nprint('captured')\n")
    done = subprocess.run([sys.executable, "-m", "pycodecad", "check", str(script)], capture_output=True,
                          env=python_env(), timeout=60)
    report = json.loads(done.stdout)
    assert done.returncode == 0 and report["stdout"] == "captured\n" and b"native output" in done.stderr


@pytest.mark.parametrize("args, message", [
    (["export", "part.py", "out.obj"], "cannot export out.obj"),
    (["export", "part.py", "out.stl", "--profile", "bambu"], "--profile is only for .3mf"),
    (["export", "part.py", "missing/out.stl"], "does not exist"),
    (["render", "part.py", "out.jpg"], "must end in .png"),
    (["render", "part.py", "out.png", "--size", "0x0"], "--size must look like"),
    (["render", "part.py", "out.png", "--size", "9000x10"], "--size must look like"),
    (["render", "part.py", "out.png", "--views", "window,iso"], "do not combine it with other views"),
    (["render", "part.py", "out.png", "--views", "iso,sideways"], "Unknown view 'sideways'"),
    (["render", "part.py", "missing/out.png"], "does not exist"),
    (["check", "missing.py"], "No such file or directory"),
    (["check", "."], "Permission denied" if os.name == "nt" else "Is a directory"),
    (["check", "latin.py"], "not a UTF-8 text file"),
])
def test_bad_command_lines_fail_cleanly_before_running(tmp_path, monkeypatch, capsys, args, message):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "part.py").write_text("raise SystemExit('the script must not run')\n")
    (tmp_path / "latin.py").write_bytes(b"name = '\xe9'\n")
    assert main(args) == 1
    output = capsys.readouterr()
    assert output.err.startswith("pycodecad: ") and message in output.err and not output.out
    assert not (tmp_path / ".pycodecad").exists()


def test_render_has_no_view_option(tmp_path, capsys):
    (tmp_path / "part.py").write_text(PART)
    with pytest.raises(SystemExit):
        main(["render", str(tmp_path / "part.py"), str(tmp_path / "out.png"), "--view", "front"])
    assert "unrecognized arguments: --view front" in capsys.readouterr().err
    assert not (tmp_path / "out.png").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal delivery")
@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM])
def test_ctrl_c_stops_the_script(tmp_path, stop):
    command, child = start_endless(tmp_path, "check", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    command.send_signal(stop)
    out, err = command.communicate(timeout=10)
    assert command.returncode == 130 and err.decode().strip() == "pycodecad: interrupted" and not out
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    assert json.loads((tmp_path / ".pycodecad" / "part.py.last-run.json").read_text())["error"] == "Stopped"


def test_context_quotes_paths_in_commands(tmp_path, capsys):
    folder = tmp_path / "sub dir"
    folder.mkdir()
    script = folder / "part 1.py"
    script.write_text(PART)
    assert main(["context", str(script)]) == 0
    text = capsys.readouterr().out
    assert "check 'part 1.py'" in text and "export 'part 1.py' 'part 1.stl'" in text
    assert "`python 'part 1.py'`" in text and ".pycodecad/part 1.py.last-run.json" in text


@pytest.mark.parametrize("entrypoint", ["path", "absolute", "module"])
def test_windows_context_uses_literal_powershell_paths(tmp_path, monkeypatch, entrypoint):
    from pycodecad import context

    folder = tmp_path / "Python & $tools d'atelier"
    folder.mkdir()
    executable = folder / "python.exe"
    console = folder / "pycodecad.exe"
    if entrypoint != "module":
        console.touch()
    monkeypatch.setattr(context, "WINDOWS", True)
    monkeypatch.setattr(context.sys, "executable", str(executable))
    monkeypatch.setattr(context.shutil, "which", lambda name: str(console) if entrypoint == "path" else None)
    script = folder / "part d'été $size & 1.py"
    text = context.ai_context(script)
    command = ("pycodecad" if entrypoint == "path" else
               "& '" + str(console if entrypoint == "absolute" else executable).replace("'", "''") + "'"
               + (" -m pycodecad" if entrypoint == "module" else ""))
    assert "Run the commands below in PowerShell." in text
    assert f"{command} check 'part d''été $size & 1.py'" in text
    assert f"{command} export 'part d''été $size & 1.py' 'part d''été $size & 1.stl'" in text


def test_context_prints_on_a_non_utf8_console(tmp_path):
    script = tmp_path / "part_雪.py"
    script.write_text("print('pièce 雪')\n", encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "pycodecad", "context", str(script)],
                          env=python_env() | {"PYTHONIOENCODING": "ascii:strict"}, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr.decode("ascii")
    assert "part_\\u96ea.py" in done.stdout.decode("ascii")
    assert "pi\\xe8ce \\u96ea" in done.stdout.decode("ascii")


EXPOSED = """\
from typing import Annotated
from build123d import Box
from pytypehint import Label, Max, Min, Slider
from pycodecad import expose, show


def box(width: Annotated[float, Min(20.0), Max(200.0), Slider(), Label("Width")] = 60.0,
        height: Annotated[int, Min(5)] = 30, hollow: bool = False, text: str = "hi"):
    print(repr(width), repr(height), repr(hollow), repr(text))
    return Box(width, 10, height)


show(expose(box), name="box")
"""


def test_set_passes_typed_values_to_expose(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    assert main(["check", str(script)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stdout"] == "60.0 30 False 'hi'\n"
    assert main(["check", str(script), "--set", "width=80", "--set", "box.height=12",
                 "--set", "hollow=yes", "--set", "text=a=b "]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stdout"] == "80.0 12 True 'a=b '\n"
    assert report["objects"][0]["bbox"] == {"min": [-40, -5, -6], "max": [40, 5, 6]}
    assert [(p["name"], p["value"]) for p in report["parameters"][0]["params"]] == [
        ("width", 80.0), ("height", 12), ("hollow", True), ("text", "a=b ")]


@pytest.mark.parametrize("setting, message", [
    ("depth=3", "No exposed parameter depth"),
    ("other.width=3", "No exposed parameter other.width"),
    ("height=tall", "'tall' is not a valid int"),
    ("hollow=maybe", "not a valid bool"),
    ("width=500", "width"),
])
def test_set_unknown_key_or_bad_value_is_the_run_error(tmp_path, capsys, setting, message):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    assert main(["check", str(script), "--set", setting]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["ok"] and message in report["error"]
    assert main(["export", str(script), str(tmp_path / "out.stl"), "--set", setting]) == 1
    assert message in capsys.readouterr().err and not (tmp_path / "out.stl").exists()


@pytest.mark.parametrize("setting", ["width", "=80", " =80"])
def test_malformed_set_is_an_argparse_error(tmp_path, capsys, setting):
    (tmp_path / "part.py").write_text("raise SystemExit('the script must not run')\n")
    for args in (["check"], ["render", str(tmp_path / "out.png")], ["export", str(tmp_path / "out.stl")]):
        with pytest.raises(SystemExit) as exit:
            main([args[0], str(tmp_path / "part.py"), *args[1:], "--set", setting])
        assert exit.value.code == 2 and "must look like KEY=VALUE" in capsys.readouterr().err
    assert not (tmp_path / ".pycodecad").exists()


def test_export_with_set(tmp_path, capsys):
    from pycodecad.files import read_triangles

    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    assert main(["export", str(script), str(tmp_path / "out.stl"), "--set", "width=100"]) == 0
    assert "Wrote" in capsys.readouterr().out
    points = read_triangles(tmp_path / "out.stl").reshape(-1, 3)
    assert round(float(points[:, 0].max() - points[:, 0].min()), 3) == 100


@needs_gl
def test_render_with_set(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    assert main(["render", str(script), str(tmp_path / "out.png"), "--size", "64x48", "--set", "width=30"]) == 0
    assert png_size(tmp_path / "out.png") == (64, 48)
    report = json.loads((tmp_path / ".pycodecad" / "part.py.last-run.json").read_text())
    assert report["parameters"][0]["params"][0]["value"] == 30.0


def test_context_explains_expose_and_lists_parameters(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    assert main(["context", str(script)]) == 0
    text = capsys.readouterr().out
    for expected in ("import show, clear, frame, import_mesh, expose", "show(expose(box))",
                     "render part.py out.png --set width=80", "## Exposed parameters",
                     "- box():", "  - width = 60.0 (float, 20..200, slider, label 'Width')",
                     "  - height = 30 (int, 5..)", "  - hollow = False (bool)", "  - text = 'hi' (str)"):
        assert expected in text
    script.write_text(PART)
    assert main(["context", str(script)]) == 0
    assert "## Exposed parameters" not in capsys.readouterr().out


def test_examples_are_copied_once_and_opened(tmp_path, monkeypatch):
    import pycodecad.app

    opened = []
    monkeypatch.setattr(pycodecad.app, "open_window", lambda path, run=True: opened.append((path, run)))
    target = tmp_path / "ex"
    assert main(["examples", str(target), "--no-run"]) == 0
    assert (target / "parts.py").is_file() and (target / "assembly.py").is_file()
    assert not (target / "__pycache__").exists()
    (target / "parts.py").write_text("# mine\n")
    assert main(["examples", str(target)]) == 0
    assert (target / "parts.py").read_text() == "# mine\n"
    assert opened == [(str(target), False), (str(target), True)]
