import json

import numpy as np

from conftest import needs_gl
from pycodecad import runner
from pycodecad.cli import main

ANIMATION = """from build123d import Box, Pos
from pycodecad import clear, frame, show
box = Box(10, 10, 10)
for x in (0, 20, 40):
    clear()
    show(Pos(x, 0, 0) * box, name="box")
    show(Pos(0, 50, 0) * box, name="still")
    frame()
"""


def run(code, filename="<editor>"):
    return runner.Run(code, filename).wait(60)


def test_each_frame_is_the_scene_when_frame_was_called():
    result = run(ANIMATION)
    assert result.error is None and len(result.frames) == 3
    boxes = [frame[0].bbox() for frame in result.frames]
    lefts = [box[0][0] for box in boxes if box is not None]
    assert np.allclose(lefts, [-5, 15, 35])
    assert all([obj.name for obj in frame] == ["box", "still"] for frame in result.frames)


def test_moved_copies_share_one_mesh_and_volume():
    result = run(ANIMATION)
    meshes = {id(obj.mesh) for frame in result.frames for obj in frame}
    assert len(meshes) == 1
    volumes = {obj.volume for frame in result.frames for obj in frame}
    volume = volumes.pop()
    assert not volumes and volume is not None and abs(volume - 1000.0) < 1e-6


def test_a_moved_object_is_placed_in_world_coordinates():
    result = run("from build123d import Box, Pos, Rot\nfrom pycodecad import show\n"
                 "show(Pos(100, 0, 0) * Rot(0, 0, 90) * Box(10, 20, 30))\n")
    obj, = result.shown
    box, world = obj.bbox(), obj.world().bbox()
    assert obj.matrix is not None and box is not None and world is not None
    assert np.allclose(box[0], (90, -5, -15)) and np.allclose(box[1], (110, 5, 15))
    assert np.allclose(world, box)


def test_a_rotated_cylinder_keeps_its_reported_diameter():
    result = run("from build123d import Cylinder, Pos, Rot\nfrom pycodecad import show\n"
                 "show(Pos(20, 30, 0) * Rot(0, 0, 45) * Cylinder(5, 10))\n")
    assert result.error is None, result.error
    report = runner.report("<editor>", result)
    bounds = report["objects"][0]["bbox"]
    # Tessellation approximates the circular surface; rotating about Z cannot enlarge its diameter.
    assert np.allclose(bounds["min"], [15, 25, -5], atol=0.02)
    assert np.allclose(bounds["max"], [25, 35, 5], atol=0.02)


def test_without_frame_the_scene_is_still():
    result = run("from build123d import Box\nfrom pycodecad import show\nshow(Box(1, 1, 1))\n")
    assert result.frames == [] and len(result.shown) == 1


def test_frames_alone_are_not_nothing_shown():
    result = run(ANIMATION + "clear()\n")
    assert result.shown == [] and len(result.frames) == 3
    assert runner.NOTHING_SHOWN not in result.warnings


def test_check_reports_the_frames(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(ANIMATION)
    assert main(["check", str(script)]) == 0
    assert json.loads(capsys.readouterr().out)["frames"] == 3


@needs_gl
def test_render_a_frame(tmp_path, capsys):
    script = tmp_path / "part.py"
    script.write_text(ANIMATION)
    assert main(["render", str(script), str(tmp_path / "a.png"), "--frame", "2"]) == 0
    assert (tmp_path / "a.png").read_bytes().startswith(b"\x89PNG")
    assert main(["render", str(script), str(tmp_path / "b.png"), "--frame", "4"]) == 1
    assert "the script made 3 frames" in capsys.readouterr().err


def test_the_workspace_plays_and_seeks(tmp_path):
    from pycodecad.workspace import Workspace

    script = tmp_path / "part.py"
    script.write_text(ANIMATION)
    ws = Workspace(str(script), run=False)
    ws.start_run()
    assert ws.child is not None
    ws.child.finished.wait(60)
    ws.check_runs()
    assert len(ws.frames) == 3 and ws.playing
    assert ws.on_screen() is ws.frames[0]
    ws.seek(2)
    assert not ws.playing and ws.on_screen() is ws.frames[2]
