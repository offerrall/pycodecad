"""pycodecad.embed: the components drawn in a hidden window's ImGui frames."""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import glfw
import pytest
from slimgui import imgui

from conftest import needs_display, tetrahedron
from pycodecad import camera as cam, textedit, ui
from pycodecad.cad import Shown
from pycodecad.embed import Viewer, Workspace, create_window

pytestmark = needs_display
EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def window():
    window = create_window("embed test", size=(900, 600), visible=False)
    yield window
    window.close()


def frames(window, draw, until, limit=30.0):
    """Frames (without waiting for input) until until() holds after one."""
    deadline = time.monotonic() + limit
    while True:
        window.timeout = 0.0
        assert window.frame()
        draw()
        if until():
            return
        assert time.monotonic() < deadline, "timed out"


def in_window(title, draw):
    def frame():
        imgui.begin(title)
        draw()
        imgui.end()
    return frame


def test_two_viewers_are_independent(window):
    objects = [Shown(name="t", color=(0.8, 0.5, 0.2), mesh=tetrahedron())]
    first, second = Viewer(), Viewer()

    def draw():
        in_window("A", lambda: first.draw(objects))()
        in_window("B", lambda: second.draw(objects, (200.0, 100.0)))()

    frames(window, draw, lambda: True)
    assert not first.fit_pending and first.camera == second.camera  # both fit the first objects
    assert second.size == (200, 100) and first.size != second.size
    first.camera = cam.orbit(first.camera, 50.0, 0.0)
    frames(window, draw, lambda: True)
    assert first.camera != second.camera and first.objects == second.objects == objects
    assert first.renderer is not None and first.renderer is not second.renderer
    assert first.picture()[:8] == b"\x89PNG\r\n\x1a\n"
    window.close()
    assert first.renderer is None and second.renderer is None  # closed with the window


EXPOSED = ("from build123d import Box\nfrom pycodecad import expose, show\n"
           "def box(size: float = 10.0):\n    print(size)\n    return Box(size, size, size)\nshow(expose(box))\n")


def test_a_workspace_in_a_host_window(window, tmp_path):
    script = tmp_path / "part.py"
    script.write_text(EXPOSED)
    part = Workspace(script, run=False)
    viewer = Viewer()

    def draw():
        in_window("Part", part.draw)()
        in_window("Preview", lambda: viewer.draw(part.shown))()

    window.gui.events.append((glfw.KEY_R, glfw.MOD_CONTROL, False))  # the shortcuts work from the start
    frames(window, draw, lambda: part.ran() and not part.running())
    assert part.error is None and part.stdout.strip() == "10.0" and len(part.shown) == 1
    part.values["box.size"] = 25.0
    part.run()
    frames(window, draw, lambda: not part.running())
    assert part.stdout.strip() == "25.0" and viewer.objects == part.shown
    part.export("stl", target="order_1.stl")
    frames(window, draw, lambda: not part.exports)
    assert (tmp_path / "order_1.stl").is_file() and part.message == f"Exported {tmp_path / 'order_1.stl'}"
    part.editor = textedit.insert(part.editor, "# edited\n")
    window.gui.events.append((glfw.KEY_S, glfw.MOD_CONTROL, False))
    frames(window, draw, lambda: True)  # the Preview window has the focus: the keys are not for the part
    assert part.dirty()
    window.gui.events.append((glfw.KEY_S, glfw.MOD_CONTROL, False))
    frames(window, lambda: (imgui.set_next_window_focus(), draw()), lambda: True)  # e.g. a click on it
    assert script.read_text().startswith("# edited\n") and not part.dirty()


def test_read_only_shortcuts_run_parameters_and_export_without_editing(window, tmp_path):
    from pycodecad.files import read_triangles

    script = tmp_path / "template.py"
    script.write_text(EXPOSED)
    before = script.stat().st_mtime_ns
    part = Workspace(script, read_only=True, run=False)
    draw = in_window("Template", part.draw)
    frames(window, draw, lambda: True)
    assert not part.ran()

    part.values["box.size"] = 25.0
    window.gui.events.extend([
        "unwanted edit",
        (glfw.KEY_S, glfw.MOD_CONTROL, False),
        (glfw.KEY_S, glfw.MOD_CONTROL | glfw.MOD_SHIFT, False),
        (glfw.KEY_R, glfw.MOD_CONTROL, False),
    ])
    frames(window, draw, lambda: part.ran() and not part.running())
    assert part.error is None and part.stdout.strip() == "25.0"
    assert part.editor.text == EXPOSED and not part.dirty() and not part.save_as_open
    assert part.shown[0].bbox() == ((-12.5, -12.5, -12.5), (12.5, 12.5, 12.5))

    part.values["box.size"] = 30.0  # not run yet: Export must still match the view
    part.export("stl")
    frames(window, draw, lambda: not part.exports)
    assert not part.message_is_error, part.message
    points = read_triangles(tmp_path / "template.stl")
    assert points.min(axis=0).tolist() == [-12.5, -12.5, -12.5]
    assert points.max(axis=0).tolist() == [12.5, 12.5, 12.5]
    assert script.read_text() == EXPOSED and script.stat().st_mtime_ns == before
    assert sorted(path.name for path in tmp_path.glob("*.py")) == ["template.py"]


def test_closing_with_unsaved_changes_asks_first(window, tmp_path, monkeypatch):
    script = tmp_path / "part.py"
    script.write_text("a = 1\n")
    part = Workspace(script, run=False)
    part.editor = textedit.insert(part.editor, "b = 2\n")

    def draw():
        in_window("Part", part.draw)()
        part.close_prompt(window)

    window.request_close()  # the user closes the window
    for _ in range(3):
        window.timeout = 0.0
        assert window.frame(keep_open=part.dirty())  # kept open: the prompt asks
        draw()
        assert window.close_requested
    real = imgui.button
    monkeypatch.setattr(ui.imgui, "button", lambda label, *args: label == "Discard" or real(label, *args))
    draw()  # Discard: the edits go, and the window closes
    assert not part.dirty() and script.read_text() == "a = 1\n"
    assert not window.frame(keep_open=part.dirty())


def test_the_embedded_example_runs(tmp_path):
    for name in ("embedded_app.py", "tray.py"):
        shutil.copy(EXAMPLES / name, tmp_path)
    picture = tmp_path / "shot.png"
    subprocess.run([sys.executable, str(tmp_path / "embedded_app.py"), str(picture)], timeout=60, check=True)
    assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "tray.py").read_text() == (EXAMPLES / "tray.py").read_text()


def test_a_glfw_window_of_the_host(tmp_path):
    import moderngl

    from pycodecad.embed import Window

    assert glfw.init()
    glfw.window_hint(glfw.VISIBLE, False)
    for hint, value in ((glfw.CONTEXT_VERSION_MAJOR, 3), (glfw.CONTEXT_VERSION_MINOR, 3),
                        (glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE), (glfw.OPENGL_FORWARD_COMPAT, True)):
        glfw.window_hint(hint, value)
    handle = glfw.create_window(400, 300, "host", None, None)
    glfw.make_context_current(handle)
    ctx = moderngl.create_context()  # the host's own moderngl context and key callback

    def host_keys(*args):
        pass

    glfw.set_key_callback(handle, host_keys)
    try:
        window = Window(handle, ctx=ctx)
        assert window.ctx is ctx
        texture = ctx.texture((4, 4), 4, b"\xff" * 64)  # the host's own picture
        frames(window, in_window("Host", lambda: imgui.image(texture.glo, (4.0, 4.0))), lambda: True)
        window.screenshot(str(tmp_path / "host.png"))
        assert window.frame()  # shows the frame (the texture bound by its GL name)
        window.close()
        assert (tmp_path / "host.png").is_file() and not glfw.window_should_close(handle)  # still the host's
        assert glfw.set_key_callback(handle, None) is host_keys  # pyright: ignore[reportArgumentType]  # its callbacks are back
        assert glfw.set_char_callback(handle, None) is None  # pyright: ignore[reportArgumentType]  # (none before: none now)
        ctx.texture((1, 1), 4).release()  # and its context still works
    finally:
        ctx.release()
        glfw.destroy_window(handle)
        glfw.terminate()


def test_the_file_list_and_opening_another_file_with_unsaved_changes(window, tmp_path, monkeypatch):
    (tmp_path / "helper.py").write_text("def size():\n    return 1 / 0\n")
    (tmp_path / "part.py").write_text("import helper\nfrom pycodecad import show\nshow(helper.size())\n")
    part = Workspace(tmp_path)
    draw = in_window("Part", part.draw)
    frames(window, draw, lambda: part.ran() and not part.running())
    assert part.error_file == str(tmp_path / "helper.py") and part.path.name == "part.py"
    part.editor = textedit.insert(part.editor, "# mine\n")
    with monkeypatch.context() as patch:
        patch.setattr(ui.imgui, "is_item_clicked", lambda *args: True)  # a click on "in helper.py, line 2"
        frames(window, draw, lambda: True)
    assert part.opening == (tmp_path / "helper.py", 2) and part.path.name == "part.py"  # the prompt asks
    real = imgui.button
    with monkeypatch.context() as patch:
        patch.setattr(ui.imgui, "button", lambda label, *args: label == "Save" or real(label, *args))
        frames(window, draw, lambda: part.opening is None)
    assert part.path.name == "helper.py" and textedit.line_col(part.editor.text, part.editor.cursor) == (1, 0)
    assert (tmp_path / "part.py").read_text().startswith("# mine\n") and not part.dirty()
    selectable = imgui.selectable
    with monkeypatch.context() as patch:  # a click on part.py in the list
        patch.setattr(ui.imgui, "selectable", lambda label, *args: (True, True) if label == "##part.py"
                      else selectable(label, *args))
        frames(window, draw, lambda: True)
    assert part.path.name == "part.py" and part.main.name == "part.py"
