"""Orbit camera around a target point. Z is up; angles in degrees.

Matrices are 16 floats in column-major order, the layout GL uniforms expect.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Annotated

from pytypehint import Max, Min, immutable

Vec = tuple[float, float, float]
BBox = tuple[Vec, Vec]  # (min corner, max corner)

VIEWS = {  # name -> (yaw, pitch)
    "iso": (315.0, 35.264), "front": (270.0, 0.0), "back": (90.0, 0.0), "left": (180.0, 0.0),
    "right": (0.0, 0.0), "top": (270.0, 89.0), "bottom": (270.0, -89.0),
}


@immutable
class Camera:
    """Looks at target from distance away; yaw turns around Z (0 looks from +X), pitch tilts up."""
    target: Vec = (0.0, 0.0, 0.0)
    distance: Annotated[float, Min(1e-6), Max(1e12)] = 100.0
    yaw: Annotated[float, Min(0.0), Max(360.0, exclusive=True)] = 315.0
    pitch: Annotated[float, Min(-89.0), Max(89.0)] = 35.264
    fov: Annotated[float, Min(0.0, exclusive=True), Max(180.0, exclusive=True)] = 45.0


def wrap_yaw(degrees: float) -> float:
    """Any angle as a yaw in [0, 360)."""
    yaw = float(degrees) % 360.0
    return 0.0 if yaw == 360.0 else yaw  # a tiny negative angle rounds up to 360


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def basis(cam: Camera) -> tuple[Vec, Vec, Vec]:
    """Right, up and back unit vectors."""
    yaw, pitch = math.radians(cam.yaw), math.radians(cam.pitch)
    back = (math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))
    right = (-math.sin(yaw), math.cos(yaw), 0.0)
    up = (back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2],
          back[0] * right[1] - back[1] * right[0])
    return right, up, back


def orbit(cam: Camera, dx: float, dy: float) -> Camera:
    return replace(cam, yaw=wrap_yaw(cam.yaw - dx * 0.35), pitch=clamp(cam.pitch + dy * 0.35, -89.0, 89.0))


def pan(cam: Camera, dx: float, dy: float, height: float) -> Camera:
    """Move by pixels; height is the shorter viewport side (the axis the fov spans)."""
    right, up, _ = basis(cam)
    scale = 2 * cam.distance * math.tan(math.radians(cam.fov / 2)) / max(height, 1.0)
    target = tuple(float(t - r * dx * scale + u * dy * scale) for t, r, u in zip(cam.target, right, up))
    return replace(cam, target=target)


def zoom(cam: Camera, wheel: float) -> Camera:
    return replace(cam, distance=clamp(cam.distance * math.exp(-wheel * 0.12), 1e-6, 1e12))


def check_view(view: str, *others: str) -> None:
    """Raise ValueError unless `view` is one of VIEWS (or of `others`)."""
    if view not in VIEWS and view not in others:
        raise ValueError(f"Unknown view {view!r}: use one of {', '.join([*VIEWS, *others])}")


def set_view(cam: Camera, view: str) -> Camera:
    check_view(view)
    yaw, pitch = VIEWS[view]
    return replace(cam, yaw=yaw, pitch=pitch)


def look_from(cam: Camera, direction: Vec) -> Camera:
    """Look at the target from a direction (any length): (0, -1, 0) is the front view, (1, -1, 1) iso."""
    x, y, z = direction
    flat = math.hypot(x, y)
    yaw = wrap_yaw(math.degrees(math.atan2(y, x))) if flat > 1e-9 else VIEWS["top"][0]  # straight down: front at the bottom
    pitch = clamp(math.degrees(math.atan2(z, flat)), -89.0, 89.0)
    return replace(cam, yaw=yaw, pitch=pitch)


def fit(cam: Camera, bbox: BBox) -> Camera:
    """Frame the bounding sphere of the box with a small margin."""
    lo, hi = bbox
    radius = max(math.dist(lo, hi) / 2, 1e-5)
    target = tuple(float((a + b) / 2) for a, b in zip(lo, hi))
    distance = clamp(radius / math.sin(math.radians(cam.fov / 2)) * 1.15, 1e-6, 1e12)
    return replace(cam, target=target, distance=distance)


def needs_fit(previous: BBox | None, current: BBox | None) -> bool:
    """Keep the view for small edits; refit after a 2x size change or a large move."""
    if current is None:
        return False
    if previous is None:
        return True
    old_size = max(math.dist(*previous), 1e-5)
    new_size = max(math.dist(*current), 1e-5)
    old_center = [(a + b) / 2 for a, b in zip(*previous)]
    new_center = [(a + b) / 2 for a, b in zip(*current)]
    return not old_size / 2 < new_size < old_size * 2 or math.dist(old_center, new_center) > old_size / 2


def matrices(cam: Camera, aspect: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(view, projection) matrices; the fov spans the shorter side of the viewport."""
    right, up, back = basis(cam)
    eye = tuple(t + b * cam.distance for t, b in zip(cam.target, back))
    dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    view = (right[0], up[0], back[0], 0.0,
            right[1], up[1], back[1], 0.0,
            right[2], up[2], back[2], 0.0,
            -dot(right, eye), -dot(up, eye), -dot(back, eye), 1.0)
    near, far = max(cam.distance * 0.001, 1e-8), cam.distance * 100
    aspect = max(aspect, 1e-6)
    f = min(1.0, aspect) / math.tan(math.radians(cam.fov / 2))
    projection = (f / aspect, 0.0, 0.0, 0.0,
                  0.0, f, 0.0, 0.0,
                  0.0, 0.0, (far + near) / (near - far), -1.0,
                  0.0, 0.0, 2 * far * near / (near - far), 0.0)
    return view, projection


def scene_bbox(boxes: list[BBox | None]) -> BBox | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    low_x, low_y, low_z = zip(*(low for low, _ in present))
    high_x, high_y, high_z = zip(*(high for _, high in present))
    return (min(low_x), min(low_y), min(low_z)), (max(high_x), max(high_y), max(high_z))
