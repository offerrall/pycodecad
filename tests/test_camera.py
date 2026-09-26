import json
import math
import pickle
from dataclasses import replace

import pytest

from pycodecad import camera as cam
from pycodecad.sidecar import load_camera, save_camera, sidecar


@pytest.mark.parametrize("change", [
    dict(target=(0.0, 0.0, math.inf)), dict(target=(0.0, math.nan, 0.0)), dict(target=(0, 0, 0)),
    dict(target=(0.0, 0.0)), dict(distance=0.0), dict(distance=1e13), dict(distance=100),
    dict(yaw=360.0), dict(yaw=-45.0), dict(pitch=89.5), dict(pitch=-90.0),
    dict(fov=0.0), dict(fov=180.0), dict(fov=math.nan),
])
def test_an_invalid_camera_cannot_be_built(change):
    with pytest.raises((TypeError, ValueError)):
        cam.Camera(**change)
    with pytest.raises((TypeError, ValueError)):
        replace(cam.Camera(), **change)


def test_a_camera_is_keyword_only_and_survives_pickle():
    with pytest.raises(TypeError):
        cam.Camera((0.0, 0.0, 0.0), 100.0)  # pyright: ignore[reportCallIssue]
    camera = cam.Camera(yaw=12.5, pitch=-3.0)
    assert pickle.loads(pickle.dumps(camera)) == camera


def test_every_move_builds_a_valid_camera():
    camera = cam.Camera()
    for yaw in (*[v[0] for v in cam.VIEWS.values()], camera.yaw):
        assert 0.0 <= yaw < 360.0
    assert cam.orbit(cam.Camera(yaw=0.0), 1e-15, 0.0).yaw == 0.0  # -tiny % 360 would be 360.0
    assert cam.orbit(camera, 0.0, 1e6).pitch == 89.0 and cam.orbit(camera, 0.0, -1e6).pitch == -89.0
    assert cam.zoom(camera, 1e4).distance == 1e-6 and cam.zoom(camera, -300).distance == 1e12
    assert cam.look_from(camera, (0, -1, 0)).yaw == 270.0
    assert cam.look_from(camera, (0, 0, 1)) == cam.set_view(camera, "top")
    panned = cam.pan(camera, 3, 4, 600)
    assert all(type(v) is float for v in panned.target)
    fitted = cam.fit(camera, ((0, 0, 0), (10, 10, 10)))  # integer corners become float
    assert fitted.target == (5.0, 5.0, 5.0)
    assert cam.fit(camera, ((-1e300, -1e300, -1e300), (1e300, 1e300, 1e300))).distance == 1e12


def test_the_window_camera_file(tmp_path):
    script = tmp_path / "part.py"
    camera = cam.Camera(target=(1.0, 2.0, 3.0), distance=50.0, yaw=10.0, pitch=20.0, fov=30.0)
    save_camera(script, camera, (640, 480))
    assert load_camera(script) == (camera, (640, 480))
    path = sidecar(script, "camera")
    saved = json.loads(path.read_text())
    path.write_text(json.dumps(saved | dict(yaw=-45, distance=50)))  # an older file: negative yaw, integers
    assert load_camera(script)[0] == replace(camera, yaw=315.0)
    for broken in ("{", "[]", json.dumps(saved | dict(pitch=120.0)), json.dumps(saved | dict(target=[1, 2])),
                   json.dumps(saved | dict(fov="wide")), json.dumps({k: v for k, v in saved.items() if k != "fov"}),
                   json.dumps(saved | dict(distance=None)), json.dumps(saved).replace("50.0", "Infinity")):
        path.write_text(broken)
        with pytest.raises(ValueError, match="invalid camera file"):
            load_camera(script)
    path.unlink()
    with pytest.raises(OSError):
        load_camera(script)
