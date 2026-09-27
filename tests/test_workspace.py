import json
import os
import subprocess
import sys
import time

import pytest

from conftest import needs_display
from pycodecad import textedit
from pycodecad.workspace import Workspace
from pycodecad.sidecar import sidecar


def test_new_file_is_created(tmp_path):
    ws = Workspace(str(tmp_path / "new.py"))
    assert (tmp_path / "new.py").read_text() == ws.editor.text != ""


def touch_later(path, seconds=5):
    os.utime(path, (time.time() + seconds, time.time() + seconds))


def test_it_runs_once_when_opened_then_nothing_by_itself(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("a = 1\n")
    assert Workspace(str(script)).run_requested and not Workspace(str(script), run=False).run_requested
    ws = Workspace(str(script), run=False)
    ws.editor = textedit.insert(ws.editor, "b = 2\n")
    assert ws.dirty() and script.read_text() == "a = 1\n"
    ws.save()
    assert not ws.dirty() and script.read_text() == "b = 2\na = 1\n"


def test_changes_on_disk_are_noticed_not_applied(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("a = 1\n")
    ws = Workspace(str(script), run=False)
    script.write_text("theirs = 1\n")  # e.g. an AI assistant edits the file
    touch_later(script)
    ws.watch_file()
    assert ws.disk_changed and ws.editor.text == "a = 1\n" and not ws.run_requested
    ws.reload()
    assert ws.editor.text == "theirs = 1\n" and not ws.disk_changed and not ws.dirty()
    ws.editor = textedit.insert(ws.editor, "# mine\n")
    script.write_text("theirs = 2\n")
    touch_later(script, 10)
    ws.watch_file()
    assert ws.disk_changed and ws.dirty()
    ws.save()  # Save overwrites
    assert script.read_text() == "# mine\ntheirs = 1\n" and not ws.disk_changed


def test_camera_is_saved_next_to_the_script(tmp_path):
    ws = Workspace(str(tmp_path / "part.py"))
    ws.viewer.fit_pending = False
    ws.viewer.size = (640, 480)
    ws.save_camera(100.0)
    ws.save_camera(101.5)
    saved = json.loads(sidecar(tmp_path / "part.py", "camera").read_text())
    assert saved["width"] == 640 and saved["yaw"] == ws.viewer.camera.yaw


@needs_display
def test_window_runs_the_script_and_takes_a_screenshot(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("from build123d import Box\nfrom pycodecad import show\nshow(Box(40, 30, 10))\n")
    picture = tmp_path / "window.png"
    subprocess.run([sys.executable, "-m", "pycodecad", str(script), "--screenshot", str(picture)],
                   timeout=60, check=True)
    assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_read_only_never_writes_a_script(tmp_path):
    template = tmp_path / "template.py"
    template.write_text("size = 10\n")
    ws = Workspace(str(template), read_only=True)
    ws.editor = textedit.insert(ws.editor, "# order 42\n")  # not possible in the window: no editor
    assert not ws.save() and not ws.save_as("order_42.py") and ws.message_is_error
    assert template.read_text() == "size = 10\n" and not (tmp_path / "order_42.py").exists()
    template.chmod(0o444)  # read only is only --read-only: a file that is not writable opens as usual
    try:
        assert not Workspace(str(template)).read_only
    finally:
        template.chmod(0o644)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_save_errors_keep_the_window_and_the_edits(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    script = folder / "part.py"
    script.write_text("a = 1\n")
    script.chmod(0o755)
    ws = Workspace(str(script))
    ws.editor = textedit.insert(ws.editor, "b = 2\n")
    assert ws.save() and script.stat().st_mode & 0o777 == 0o755  # permissions are kept
    ws.editor = textedit.insert(ws.editor, "c = 3\n")
    folder.chmod(0o555)  # the file is writable, its folder is not: the atomic write fails
    try:
        assert not ws.save() and ws.dirty() and ws.message_is_error and "Permission denied" in ws.message
        assert not ws.save_as(str(tmp_path / "missing" / "copy.py")) and ws.dirty()
        assert "No such file or directory" in ws.message and ws.path == script
    finally:
        folder.chmod(0o755)
    assert ws.save_as(str(tmp_path / "copy.py")) and not ws.dirty()


def test_files_that_cannot_be_opened(tmp_path):
    (tmp_path / "latin.py").write_bytes(b"name = '\xe9'\n")
    for path, read_only in ((tmp_path / "missing" / "part.py", False), (tmp_path / "latin.py", False),
                            (tmp_path / "template.py", True)):
        with pytest.raises(OSError):
            Workspace(str(path), read_only=read_only)
    assert not (tmp_path / "template.py").exists()  # read-only never creates the file


def test_a_change_right_after_saving_is_noticed(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("a = 1\n")
    ws = Workspace(str(script))
    ws.editor = textedit.insert(ws.editor, "mine = 1\n")
    ws.save()
    script.write_text("theirs = 1\n")
    touch_later(script)
    ws.watch_file()
    assert ws.disk_changed


def test_the_window_needs_a_file(capsys, tmp_path):
    from pycodecad.cli import main

    with pytest.raises(SystemExit):
        main([])
    assert "required: file" in capsys.readouterr().err
    missing = tmp_path / "missing-folder" / "part.py"
    assert main([str(missing)]) == 1
    assert f"pycodecad: {missing}: No such file or directory" in capsys.readouterr().err


def test_keys_and_typed_text_apply_in_arrival_order():
    import glfw

    from pycodecad.editor import _keyboard

    editor = _keyboard(textedit.load(""), ["a", (glfw.KEY_ENTER, 0, False), "b", (glfw.KEY_LEFT, 0, False), "c"], 10)
    assert editor.text == "a\ncb"


def test_shortcuts_work_anywhere_except_in_dialogs(tmp_path):
    import glfw
    from slimgui import imgui

    from pycodecad import ui

    context = imgui.create_context()
    try:
        io = imgui.get_io()
        io.ini_filename = None
        io.display_size = (200, 200)
        io.backend_flags |= imgui.BackendFlags.RENDERER_HAS_TEXTURES
        imgui.new_frame()
        from pycodecad.editor import _keyboard

        script = tmp_path / "part.py"
        script.write_text("")
        ws = Workspace(str(script), run=False)
        save = (glfw.KEY_S, glfw.MOD_CONTROL, False)
        events = ui.shortcuts(ws, [(glfw.KEY_F5, 0, False), "x", save, "y"])
        ws.editor = _keyboard(ws.editor, events, 10)  # the editor applies them in order
        assert ws.run_requested and script.read_text() == "x" and ws.editor.text == "xy" and ws.dirty()
        ws.editor = _keyboard(ws.editor, ui.shortcuts(ws, [save]), 10, focused=False)
        assert script.read_text() == "xy"  # the shortcut works with the editor unfocused too
        ws.editor = _keyboard(ws.editor, ui.shortcuts(ws, [(glfw.KEY_S, glfw.MOD_CONTROL | glfw.MOD_SHIFT, False)]), 10)
        assert ws.save_as_open
        for run in ((glfw.KEY_R, glfw.MOD_CONTROL, False), (glfw.KEY_ENTER, glfw.MOD_CONTROL, False)):
            ws.run_requested = False
            ws.editor = _keyboard(ws.editor, ui.shortcuts(ws, [run]), 10)
            assert ws.run_requested and ws.editor.text == "xy"
        assert ui.shortcuts(ws, [(glfw.KEY_R, glfw.MOD_CONTROL, True)]) == []  # a held key runs once
        imgui.open_popup("dialog")
        keys = [(glfw.KEY_F5, 0, False), (glfw.KEY_R, glfw.MOD_CONTROL, False), save]
        assert ui.shortcuts(ws, keys) == keys  # a dialog is open: they stay plain keys
        imgui.render()
    finally:
        imgui.destroy_context(context)


@needs_display
def test_screenshot_after_a_run_that_shows_nothing(tmp_path):
    script = tmp_path / "helper.py"
    script.write_text("def make():\n    return 1\n")
    picture = tmp_path / "window.png"
    subprocess.run([sys.executable, "-m", "pycodecad", str(script), "--screenshot", str(picture)],
                   timeout=60, check=True)
    assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_closing_waits_for_the_stopped_run_to_record_it(tmp_path, monkeypatch):
    from conftest import ENDLESS
    from pycodecad import runner

    written = runner.write_last_run

    def slow(script, result):
        time.sleep(0.5)
        written(script, result)

    monkeypatch.setattr(runner, "write_last_run", slow)
    script = tmp_path / "part.py"
    script.write_text(ENDLESS)
    ws = Workspace(str(script))
    ws.start_run()
    while not (tmp_path / "pid").exists():
        time.sleep(0.05)
    ws.close()
    assert json.loads(sidecar(script, "last-run").read_text())["error"] == "Stopped"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs X11 (XWayland) for a hidden window's clipboard")
def test_copies_in_imgui_text_fields_reach_the_system_clipboard():
    import glfw
    from slimgui import imgui

    from pycodecad.window import create_window

    glfw.init_hint(glfw.PLATFORM, glfw.PLATFORM_X11)
    window = create_window("clipboard test", visible=False)
    backend = window.gui
    try:
        for system in ("B", "C"):  # copying the same text twice still reaches the clipboard
            glfw.set_clipboard_string(None, system)  # pyright: ignore[reportArgumentType]  # glfw takes None
            backend._key(window.handle, glfw.KEY_C, 0, glfw.PRESS, glfw.MOD_CONTROL)
            backend.new_frame()
            imgui.set_clipboard_text("A")  # what a focused ImGui text field does on Ctrl+C
            backend.render()
            assert glfw.get_clipboard_string(None) == b"A"  # pyright: ignore[reportArgumentType]
    finally:
        window.close()
        glfw.init_hint(glfw.PLATFORM, glfw.ANY_PLATFORM)


EXPOSED = '''from typing import Annotated
from pytypehint import Min, Max, Slider, Label, Description
from pycodecad import expose

def box(width: Annotated[float, Min(20.0), Max(200.0), Slider(), Label("Width")] = 60.0,
        height: Annotated[int, Min(5), Description("Outer height")] = 30, hollow: bool = False,
        text: Annotated[str, Max(4)] = "hi"):
    print(width, height, hollow, text)

expose(box)
'''


def finish_run(ws):
    ws.start_run()
    ws.child.finished.wait(30)
    ws.check_runs()


def test_parameter_values_reach_the_next_run_and_reset(tmp_path):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    ws = Workspace(str(script))
    finish_run(ws)
    assert ws.error is None and ws.stdout.strip() == "60.0 30 False hi" and not ws.values_changed()
    (box,) = ws.parameters
    width, height, hollow, text = box.params
    ws.set_value("box", width, 500)  # kept within Min/Max, as its type
    ws.set_value("box", height, 1)
    ws.set_value("box", hollow, True)
    ws.set_value("box", text, "abcdef")  # Max(4) on a str is its length
    assert ws.values == {"box.width": 200.0, "box.height": 5, "box.hollow": True, "box.text": "abcd"}
    assert ws.values_changed() and ws.stdout.strip() == "60.0 30 False hi"  # nothing runs by itself
    finish_run(ws)
    assert ws.stdout.strip() == "200.0 5 True abcd" and not ws.values_changed()
    assert ws.parameters[0].params[0].value == 200.0
    ws.reset("box")
    assert ws.values == {} and ws.values_changed()  # the defaults apply on the next Run
    finish_run(ws)
    assert ws.stdout.strip() == "60.0 30 False hi" and not ws.values_changed()


def test_values_of_parameters_that_are_gone_or_changed_kind_are_dropped(tmp_path):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    ws = Workspace(str(script))
    finish_run(ws)
    width, height, hollow, text = ws.parameters[0].params
    for param, value in ((width, 80.0), (height, 10), (hollow, True), (text, "ok")):
        ws.set_value("box", param, value)
    ws.values["other.size"] = 3  # e.g. a function no longer exposed
    new = EXPOSED.replace('height: Annotated[int, Min(5), Description("Outer height")] = 30', "height: float = 30.0")
    ws.editor = textedit.replace_all(ws.editor, new.replace('text: Annotated[str, Max(4)] = "hi"', "depth: float = 1.0")
                                      .replace("hollow, text", "hollow, depth"))
    finish_run(ws)
    assert ws.error is None and ws.values == {"box.width": 80.0, "box.hollow": True}
    ws.editor = textedit.replace_all(ws.editor, "def box(:\n")  # e.g. a syntax error while editing
    ws.values["box.gone"] = 1
    finish_run(ws)  # a failed run keeps the values and the panel of the last good run
    assert ws.error and "box.gone" in ws.values and ws.parameters[0].function == "box"
    ws.editor = textedit.replace_all(ws.editor, EXPOSED.replace("hollow: bool = False", "hollow: int = 0"))
    finish_run(ws)  # a value of the old kind is skipped (the default is used), then dropped
    assert ws.error is None and ws.values == {"box.width": 80.0}
    assert ws.stdout.strip() == "80.0 30 0 hi"


def test_values_beyond_new_limits_are_dropped_but_not_ones_changed_during_the_run(tmp_path):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    ws = Workspace(str(script))
    finish_run(ws)
    width, height, hollow, text = ws.parameters[0].params
    ws.set_value("box", width, 150.0)
    finish_run(ws)
    ws.editor = textedit.replace_all(ws.editor, EXPOSED.replace("Max(200.0)", "Max(100.0)"))
    finish_run(ws)  # 150 is beyond the new Max: the run used the default and so does the panel
    assert ws.error is None and ws.stdout.strip() == "60.0 30 False hi"
    assert ws.values == {} and not ws.values_changed()
    ws.start_run()
    ws.set_value("box", height, 12)  # changed while it runs: for the next Run
    assert ws.child is not None
    ws.child.finished.wait(30)
    ws.check_runs()
    assert ws.values == {"box.height": 12} and ws.values_changed()


def test_the_parameters_panel_draws_every_kind_of_control(tmp_path):
    from slimgui import imgui

    from pycodecad import ui

    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    ws = Workspace(str(script), read_only=True)
    finish_run(ws)
    ws.set_value("box", ws.parameters[0].params[1], 12)
    context = imgui.create_context()
    try:
        io = imgui.get_io()
        io.ini_filename = None
        io.display_size = (600, 400)
        io.backend_flags |= imgui.BackendFlags.RENDERER_HAS_TEXTURES
        imgui.new_frame()
        imgui.begin("test")
        assert ui.parameters_height(ws, 1000.0) > 0.0
        ui.parameters(ws)
        imgui.end()
        imgui.render()
    finally:
        imgui.destroy_context(context)
    assert ws.values == {"box.height": 12}


@needs_display
def test_window_screenshot_with_exposed_parameters(tmp_path):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED.replace("print(width, height, hollow, text)",
                                      "from build123d import Box\n    show(Box(width, 30, height))")
                      .replace("import expose", "import expose, show"))
    picture = tmp_path / "window.png"
    subprocess.run([sys.executable, "-m", "pycodecad", str(script), "--screenshot", str(picture)],
                   timeout=60, check=True)
    assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_function_without_parameters_draws_an_empty_group(tmp_path):
    from slimgui import imgui

    from pycodecad import ui

    script = tmp_path / "part.py"
    script.write_text("from pycodecad import expose\ndef part():\n    return None\nexpose(part)\n")
    ws = Workspace(str(script))
    finish_run(ws)
    assert ws.error is None and ws.parameters[0].params == ()
    context = imgui.create_context()
    try:
        io = imgui.get_io()
        io.ini_filename = None
        io.display_size = (600, 400)
        io.backend_flags |= imgui.BackendFlags.RENDERER_HAS_TEXTURES
        imgui.new_frame()
        imgui.begin("test")
        ui.parameters(ws)
        imgui.end()
        imgui.render()
    finally:
        imgui.destroy_context(context)


def test_int_values_stay_within_the_controls_range(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("from pycodecad import expose\ndef part(n: int = 1):\n    print(n)\nexpose(part)\n")
    ws = Workspace(str(script))
    finish_run(ws)
    ws.set_value("part", ws.parameters[0].params[0], 2**40)
    assert ws.values == {"part.n": 10**9}


def test_export_uses_the_code_and_values_on_screen(tmp_path):
    script = tmp_path / "part.py"
    code = ("from typing import Annotated\nfrom build123d import Box\nfrom pytypehint import Max\n"
            "from pycodecad import expose, show\ndef part(size: Annotated[int, Max(100)] = 10):\n"
            "    return Box(size, 1, 1)\nshow(expose(part))\n")
    script.write_text(code)
    ws = Workspace(str(script))
    finish_run(ws)
    ws.set_value("part", ws.parameters[0].params[0], 20)
    finish_run(ws)
    ws.editor = textedit.replace_all(ws.editor, code.replace("Max(100)", "Max(15)"))  # edited, not run
    ws.export("stl")
    export = ws.exports[0]
    export.finished.wait(60)
    result = export.result
    assert result is not None and result.error is None and result.exported is not None
    from pycodecad.cad import Mesh, import_mesh

    mesh = import_mesh(result.exported)
    assert isinstance(mesh, Mesh)
    box = mesh.bbox()
    assert box is not None
    lo, hi = box
    assert round(hi[0] - lo[0]) == 20


def test_no_run_is_a_window_option(monkeypatch):
    import pycodecad.app
    from pycodecad import cli

    opened = []

    def open_window(path, screenshot=None, read_only=False, run=True):
        opened.append(run)

    monkeypatch.setattr(pycodecad.app, "open_window", open_window)
    cli.window(["part.py", "--no-run"])
    cli.window(["part.py"])
    assert opened == [False, True]


def test_every_icon_the_window_uses_is_in_the_bundled_font():
    import re
    from importlib import resources

    from pycodecad import icons

    source = resources.files("pycodecad").joinpath("ui.py").read_text(encoding="utf-8")
    used = set(re.findall(r'icon(?:_button)?\(\s*f?"([a-z0-9-]+)', source))
    assert {"play", "square", "save", "download", "copy", "rotate-ccw"} <= used
    assert used <= set(icons.CODEPOINTS), used - set(icons.CODEPOINTS)
    assert all(0xE000 <= code <= 0xF8FF for code in icons.CODEPOINTS.values())  # the font's private use area
    font = resources.files("pycodecad.icons").joinpath("lucide.ttf").read_bytes()
    assert font[:4] == b"\x00\x01\x00\x00" and len(font) > 100_000  # a TrueType file
    assert resources.files("pycodecad.icons").joinpath("LICENSE").is_file()


def test_code_zoom_steps_like_a_browser(tmp_path):
    script = tmp_path / "part.py"
    script.write_text("")
    ws = Workspace(str(script), run=False)
    ws.zoom_code(1)
    assert ws.code_zoom == 1.1
    for _ in range(50):
        ws.zoom_code(1)
    assert ws.code_zoom == 3.0
    for _ in range(50):
        ws.zoom_code(-1)
    assert ws.code_zoom == 0.5
    ws.zoom_code(0)
    assert ws.code_zoom == 1.0


def test_ctrl_plus_minus_and_zero_zoom_the_code(tmp_path):
    import glfw
    from slimgui import imgui

    from pycodecad import ui

    assert ui.zoom_step(glfw.KEY_KP_ADD) == 1 and ui.zoom_step(glfw.KEY_KP_SUBTRACT) == -1
    assert ui.zoom_step(glfw.KEY_KP_0) == 0 and ui.zoom_step(glfw.KEY_A) is None
    script = tmp_path / "part.py"
    script.write_text("")
    ws = Workspace(str(script), run=False)
    context = imgui.create_context()
    try:
        io = imgui.get_io()
        io.ini_filename = None
        io.display_size = (200, 200)
        io.backend_flags |= imgui.BackendFlags.RENDERER_HAS_TEXTURES
        imgui.new_frame()
        for action in ui.shortcuts(ws, [(glfw.KEY_KP_ADD, glfw.MOD_CONTROL, False)] * 2):
            action(ws.editor)
        assert ws.code_zoom == 1.25
        for action in ui.shortcuts(ws, [(glfw.KEY_KP_0, glfw.MOD_CONTROL, False)]):
            action(ws.editor)
        assert ws.code_zoom == 1.0
        imgui.end_frame()
    finally:
        imgui.destroy_context(context)


HELPED = "import helper\nfrom build123d import Box\nfrom pycodecad import show\nprint(helper.SIZE)\nshow(Box(helper.SIZE, 1, 1))\n"


def helped_part(folder):
    """A part in two files: part.py (the main: it calls show) imports helper.py."""
    (folder / "helper.py").write_text("SIZE = 10\n")
    (folder / "part.py").write_text(HELPED)
    return folder


def test_a_helper_changed_on_disk_is_noticed_until_the_next_run(tmp_path):
    helped_part(tmp_path)
    ws = Workspace(tmp_path, run=False)
    finish_run(ws)
    ws.watch_file()
    assert ws.error is None and ws.inputs_changed == []
    (tmp_path / "helper.py").write_text("SIZE = 30\n")  # e.g. an AI assistant, with part.py in the editor
    ws.watch_file()
    assert ws.inputs_changed == [str(tmp_path / "helper.py")] and not ws.disk_changed
    finish_run(ws)
    assert ws.inputs_changed == [] and "30" in ws.stdout


def test_the_main_file_of_a_folder(tmp_path):
    (tmp_path / "a_notes.py").write_text("x = 1\n")
    (tmp_path / "b_part.py").write_text("show(1)\n")
    (tmp_path / "c_part.py").write_text("show(2)\n")
    (tmp_path / ".hidden.py").write_text("show(0)\n")
    (tmp_path / "notes.txt").write_text("show(0)\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.py").write_text("show(3)\n")
    ws = Workspace(tmp_path, run=False)
    assert ws.main == ws.path == tmp_path / "b_part.py"  # the first that calls show()
    assert [path.name for path in ws.files()] == ["a_notes.py", "b_part.py", "c_part.py"]
    assert Workspace(tmp_path / "c_part.py", run=False).main == tmp_path / "c_part.py"  # the file given
    (tmp_path / "b_part.py").unlink()
    (tmp_path / "c_part.py").unlink()
    assert Workspace(tmp_path, run=False).main == tmp_path / "a_notes.py"  # none calls show(): the first
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OSError):
        Workspace(empty, read_only=True)
    assert not (empty / "part.py").exists()
    ws = Workspace(empty, run=False)  # nothing there: a new part
    assert ws.main == empty / "part.py" and (empty / "part.py").read_text() == ws.editor.text != ""


def test_switching_files_never_loses_unsaved_changes(tmp_path):
    helped_part(tmp_path)
    ws = Workspace(tmp_path, run=False)
    assert ws.main == ws.path == tmp_path / "part.py" and ws.title() == "pycodecad - part.py"
    assert ws.open("helper.py") and ws.path == tmp_path / "helper.py" and ws.editor.text == "SIZE = 10\n"
    assert ws.main == tmp_path / "part.py" and ws.title() == "pycodecad - helper.py (runs part.py)"
    ws.editor = textedit.insert(ws.editor, "# mine\n")
    assert not ws.open("part.py") and ws.path.name == "helper.py" and ws.dirty() and ws.message_is_error
    ws.discard()
    assert ws.open("part.py") and not ws.dirty()
    assert ws.open(tmp_path / "helper.py")
    ws.editor = textedit.insert(ws.editor, "# mine\n")
    ws.save()
    assert ws.open("part.py", line=4) and textedit.line_col(ws.editor.text, ws.editor.cursor) == (3, 0)
    assert (tmp_path / "helper.py").read_text() == "# mine\nSIZE = 10\n"
    assert not ws.open("missing.py") and ws.path.name == "part.py" and "missing.py" in ws.message


def test_run_runs_the_main_with_the_unsaved_edits_of_a_helper(tmp_path):
    helped_part(tmp_path)
    ws = Workspace(tmp_path)
    ws.open("helper.py")
    ws.editor = textedit.replace_all(ws.editor, "SIZE = 20\n")
    finish_run(ws)
    assert ws.error is None and ws.stdout == "20\n" and ws.dirty()
    assert (tmp_path / "helper.py").read_text() == "SIZE = 10\n"
    assert json.loads(sidecar(tmp_path / "part.py", "last-run").read_text())["ok"]
    ws.editor = textedit.replace_all(ws.editor, "SIZE = 30\n")  # edited, not run: export what is on screen
    ws.export("stl")
    export = ws.exports[0]
    export.finished.wait(60)
    assert export.result is not None and export.result.exported == str(tmp_path / "part.stl")
    from pycodecad.cad import Mesh, import_mesh

    mesh = import_mesh(tmp_path / "part.stl")
    assert isinstance(mesh, Mesh)
    box = mesh.bbox()
    assert box is not None
    lo, hi = box
    assert round(hi[0] - lo[0]) == 20
    ws.editor = textedit.replace_all(ws.editor, "SIZE = 1\nSIZE = 1 / 0\n")
    finish_run(ws)
    assert (ws.error_file, ws.error_line) == (str(tmp_path / "helper.py"), 2)


def test_an_error_in_a_helper_opens_it_at_its_line(tmp_path):
    from pycodecad import ui

    (tmp_path / "helper.py").write_text("def size():\n    return 1 / 0\n")
    (tmp_path / "part.py").write_text("import helper\nfrom pycodecad import show\nshow(helper.size())\n")
    ws = Workspace(tmp_path)
    finish_run(ws)
    assert (ws.error_file, ws.error_line) == (str(tmp_path / "helper.py"), 2)
    ws.editor = textedit.insert(ws.editor, "# mine\n")
    ui.open_file(ws, tmp_path / "helper.py", 2)  # a click on "in helper.py, line 2"
    assert ws.opening == (tmp_path / "helper.py", 2) and ws.path.name == "part.py"  # the prompt asks first
    ws.discard()
    ws.opening = None
    ui.open_file(ws, tmp_path / "helper.py", 2)
    assert ws.path.name == "helper.py" and textedit.line_col(ws.editor.text, ws.editor.cursor) == (1, 0)


def test_a_read_only_folder_runs_the_chosen_file_as_it_is_on_disk(tmp_path):
    helped_part(tmp_path)
    (tmp_path / "other.py").write_text("from build123d import Box\nfrom pycodecad import show\nshow(Box(2, 2, 2))\n")
    ws = Workspace(tmp_path, read_only=True, run=False)
    ws.choose("other.py")  # the file list's click: it becomes the main and runs
    assert ws.main == ws.path == tmp_path / "other.py" and ws.run_requested
    finish_run(ws)
    assert ws.error is None and len(ws.shown) == 1
    (tmp_path / "other.py").write_text("from build123d import Box\nfrom pycodecad import show\nshow(Box(3, 3, 3))\n")
    finish_run(ws)  # no Reload in read only: Run runs the file on disk
    assert ws.shown[0].bbox() == ((-1.5, -1.5, -1.5), (1.5, 1.5, 1.5))
    assert (tmp_path / "part.py").read_text() == HELPED


def test_the_file_list_follows_the_folder_and_the_main_can_change(tmp_path):
    helped_part(tmp_path)
    ws = Workspace(tmp_path, run=False)
    (tmp_path / "other.py").write_text("print('other')\n")
    assert [path.name for path in ws.files()] == ["helper.py", "part.py"]
    ws.watch_file()
    assert [path.name for path in ws.files()] == ["helper.py", "other.py", "part.py"]
    (tmp_path / "helper.py").unlink()
    ws.watch_file()
    assert [path.name for path in ws.files()] == ["other.py", "part.py"]
    ws.set_main("other.py")
    assert ws.main == tmp_path / "other.py" and ws.path == tmp_path / "part.py"
    finish_run(ws)
    assert ws.stdout == "other\n" and sidecar(tmp_path / "other.py", "last-run").is_file()


def test_the_window_opens_a_folder(monkeypatch, tmp_path):
    import pycodecad.app
    from pycodecad import cli

    opened = []
    monkeypatch.setattr(pycodecad.app, "open_window", lambda path, **options: opened.append(path))
    cli.window([str(tmp_path)])
    assert opened == [str(tmp_path)]


@needs_display
def test_window_screenshot_of_a_folder(tmp_path):
    helped_part(tmp_path)
    picture = tmp_path / "window.png"
    subprocess.run([sys.executable, "-m", "pycodecad", str(tmp_path), "--screenshot", str(picture)],
                   timeout=60, check=True)
    assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert json.loads(sidecar(tmp_path / "part.py", "last-run").read_text())["ok"]


def test_export_follows_what_is_on_screen_after_the_main_changes(tmp_path):
    from pycodecad.cad import Mesh, import_mesh

    for name, size in (("a.py", 10), ("b.py", 20)):
        (tmp_path / name).write_text(f"from build123d import Box\nfrom pycodecad import show\nshow(Box({size}, 1, 1))\n")
    ws = Workspace(str(tmp_path / "a.py"), run=False)
    ws.export("stl")
    assert ws.message.startswith("Nothing to export yet") and not ws.exports
    finish_run(ws)
    ws.set_main("b.py")  # not run yet: the screen still shows a.py's 10 mm box
    ws.export("stl")
    export = ws.exports[0]
    export.finished.wait(60)
    result = export.wait()
    assert result.error is None and result.exported is not None and result.exported.endswith("a.stl")
    mesh = import_mesh(result.exported)
    assert isinstance(mesh, Mesh) and (box := mesh.bbox()) is not None
    assert round(box[1][0] - box[0][0]) == 10


def test_export_asks_for_a_run_after_another_file_changed(tmp_path):
    from pycodecad.cad import Mesh, import_mesh

    helper = tmp_path / "parts" / "helper.py"  # a subfolder counts too
    helper.parent.mkdir()
    helper.write_text("SIZE = 10\n")
    (tmp_path / "part.py").write_text("from build123d import Box\nfrom parts.helper import SIZE\n"
                                      "from pycodecad import show\nshow(Box(SIZE, 1, 1))\n")
    ws = Workspace(str(tmp_path / "part.py"), run=False)
    finish_run(ws)
    helper.write_text("SIZE = 30\n")
    touch_later(helper)
    ws.export("stl")  # it would run the new helper: a 30 mm box while the screen shows 10 mm
    assert ws.message == "helper.py changed since the last run: Run again, then export" and not ws.exports
    finish_run(ws)
    ws.export("stl")
    export = ws.exports[0]
    export.finished.wait(60)
    result = export.wait()
    assert result.error is None and result.exported is not None
    mesh = import_mesh(result.exported)
    assert isinstance(mesh, Mesh) and (box := mesh.bbox()) is not None
    assert round(box[1][0] - box[0][0]) == 30
    ws.check_runs()
    ws.export("stl")  # the part.stl the first export made is an output, not a changed input
    assert ws.message.startswith("Exporting") and len(ws.exports) == 1
    (tmp_path / "parts" / "ref.stl").write_bytes(b"solid x\nendsolid x\n")  # a new input file
    ws.export("stl")
    assert ws.message.startswith("ref.stl changed since the last run")


def test_a_run_of_the_previous_main_is_not_shown_for_the_new_one(tmp_path):
    (tmp_path / "a.py").write_text("from build123d import Box\nfrom pycodecad import show\nshow(Box(10, 1, 1))\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    ws = Workspace(str(tmp_path / "a.py"), run=False)
    ws.start_run()
    ws.set_main("b.py")
    assert ws.child is not None
    ws.child.finished.wait(30)
    ws.check_runs()
    assert ws.shown == [] and ws.shown_job is None


def test_files_starting_with_dot_or_underscore_stay_out_of_the_list(tmp_path):
    from pycodecad.workspace import find_main, python_files

    for name in ("part.py", "_tool.py", ".scratch.py", "helper.py"):
        (tmp_path / name).write_text("from pycodecad import show\nshow()\n" if name != "helper.py" else "x = 1\n")
    assert [path.name for path in python_files(tmp_path)] == ["helper.py", "part.py"]
    assert find_main(tmp_path).name == "part.py"


def test_main_py_is_the_main_file_of_a_folder(tmp_path):
    from pycodecad.workspace import Workspace, find_main

    (tmp_path / "a_part.py").write_text("from pycodecad import show\nshow()\n")
    (tmp_path / "main.py").write_text("x = 1\n")  # even without show(): its name says so
    assert find_main(tmp_path).name == "main.py"
    assert Workspace(tmp_path / "a_part.py", run=False).main.name == "a_part.py"  # an opened file wins
