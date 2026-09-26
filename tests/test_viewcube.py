import math
from dataclasses import replace

import pytest

from pycodecad import camera as cam
from pycodecad import viewcube
from pycodecad.renderer import Display

CENTER, RADIUS = (100.0, 100.0), 30.0


def labels(camera):
    return {face.label for face in viewcube.faces(camera, CENTER, RADIUS)}


def test_the_cube_shows_the_faces_the_camera_sees():
    assert labels(cam.set_view(cam.Camera(), "iso")) == {"TOP", "FRONT", "RIGHT"}
    assert labels(cam.set_view(cam.Camera(), "front")) == {"FRONT"}
    assert labels(cam.set_view(cam.Camera(), "back")) == {"BACK"}
    assert labels(cam.Camera(yaw=135.0, pitch=-30.0)) == {"BACK", "LEFT", "BOTTOM"}
    top = viewcube.faces(cam.set_view(cam.Camera(), "top"), CENTER, RADIUS)
    assert [face.label for face in top if face.facing > 0.9] == ["TOP"]


def test_faces_project_around_the_center_and_turn_with_the_camera():
    (front,) = [f for f in viewcube.faces(cam.set_view(cam.Camera(), "front"), CENTER, RADIUS) if f.facing > 0.9]
    xs, ys = [x for x, _ in front.quad], [y for _, y in front.quad]
    assert math.isclose(min(xs), 70.0) and math.isclose(max(xs), 130.0)
    assert math.isclose(min(ys), 70.0) and math.isclose(max(ys), 130.0)
    assert math.isclose(front.center[0], 100.0) and math.isclose(front.center[1], 100.0)
    iso = {f.label: f for f in viewcube.faces(cam.set_view(cam.Camera(), "iso"), CENTER, RADIUS)}
    assert iso["TOP"].center[1] < CENTER[1] < iso["FRONT"].center[1]  # the top face is above, on screen
    assert iso["FRONT"].center[0] < CENTER[0] < iso["RIGHT"].center[0]  # front on the left, right on the right
    assert len({round(face.light, 2) for face in iso.values()}) == 3  # each face its own shade


def test_clicks_pick_a_face_an_edge_or_a_corner():
    front = viewcube.faces(cam.set_view(cam.Camera(), "front"), CENTER, RADIUS)
    assert viewcube.hit(front, CENTER) == (0, -1, 0)
    assert viewcube.hit(front, (100.0, 72.0)) == (0, -1, 1)  # the top edge
    assert viewcube.hit(front, (128.0, 72.0)) == (1, -1, 1)  # the top right corner: iso
    assert viewcube.hit(front, (72.0, 128.0)) == (-1, -1, -1)
    assert viewcube.hit(front, (135.0, 100.0)) is None  # beside the cube
    iso = viewcube.faces(cam.set_view(cam.Camera(), "iso"), CENTER, RADIUS)
    assert viewcube.hit(iso, CENTER) == (1, -1, 1)  # the corner nearest the camera
    for face in iso:
        assert viewcube.hit(iso, face.center) == face.normal


def test_a_click_looks_from_its_direction():
    directions = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (-1, 0, 0), "right": (1, 0, 0),
                  "top": (0, 0, 1), "bottom": (0, 0, -1), "iso": (1, -1, 1)}
    for view, direction in directions.items():  # the same views as the named ones
        expected, turned = cam.set_view(cam.Camera(), view), cam.look_from(cam.Camera(), direction)
        assert math.isclose(turned.yaw % 360, expected.yaw % 360, abs_tol=1e-3), view
        assert math.isclose(turned.pitch, expected.pitch, abs_tol=1e-3), view
    edge = cam.look_from(cam.Camera(), (0, -1, 1))
    assert math.isclose(edge.yaw, 270.0) and math.isclose(edge.pitch, 45.0)
    assert viewcube.name((0, -1, 1)) == "Top front" and viewcube.name((1, -1, 1)) == "Top front right (iso)"


def test_inside_a_quad_either_winding():
    quad = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    assert viewcube.inside((5.0, 5.0), quad) and viewcube.inside((5.0, 5.0), quad[::-1])
    assert viewcube.inside((0.0, 5.0), quad) and not viewcube.inside((11.0, 5.0), quad)


def valid_face(**changes):
    (face,) = [f for f in viewcube.faces(cam.set_view(cam.Camera(), "front"), CENTER, RADIUS) if f.facing > 0.9]
    return replace(face, **changes)


def test_a_face_cannot_be_invalid():
    face = valid_face()
    assert replace(face) == face
    bad = [dict(label="SIDE"), dict(normal=(0, 1, 0)), dict(normal=(0, -2, 0)), dict(normal=(0.0, -1.0, 0.0)),
           dict(facing=0.0), dict(facing=1.5), dict(light=-0.1), dict(light=1.1), dict(quad=face.quad[:3]),
           dict(center=(1, 2)), dict(cells=face.cells[:8]), dict(cells=face.cells[:8] + face.cells[:1]),
           dict(cells=((((1, 0, 0), face.quad),) + face.cells[1:]))]
    for changes in bad:
        with pytest.raises((TypeError, ValueError)):
            valid_face(**changes)


def test_display_is_immutable():
    display = Display()
    assert (display.edges, display.grid, display.axes) == (True, True, True)
    assert replace(display, grid=False) == Display(edges=True, grid=False, axes=True)
    with pytest.raises(Exception):
        display.grid = False  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises((TypeError, ValueError)):
        Display(grid=1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        Display(False, True, True)  # pyright: ignore[reportCallIssue]  # keywords only
