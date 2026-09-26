"""CAD objects to triangles: the Mesh type, colors, tessellation and import_mesh.

Importing this module is cheap: build123d/OCP are imported inside the functions that need them.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import numpy as np

if TYPE_CHECKING:
    from build123d.topology import Shape

Vec = tuple[float, float, float]
Color = tuple[float, float, float]
Matrix = tuple[float, ...]  # 4x4, row by row: where a mesh in its own coordinates is placed
# import_mesh(solid=True) needs a temporary STL; it goes here, not to /tmp (often RAM).
TEMP = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pycodecad" / "tmp"

PALETTE = ("#F4B02A", "#6947AE", "#48B5A4", "#5898DA", "#E87769", "#AAC86A")
NAMED_COLORS = dict(red="#FF0000", green="#008000", blue="#0000FF", gold="#FFD700", violet="#EE82EE",
                    purple="#800080", white="#FFFFFF", black="#000000", gray="#808080", grey="#808080",
                    orange="#FFA500", yellow="#FFFF00", cyan="#00FFFF", magenta="#FF00FF")


@dataclass(frozen=True)
class Mesh:
    """Triangles (positions/normals, 3 rows per triangle) and edge segments (2 rows per segment)."""

    positions: np.ndarray
    normals: np.ndarray
    edges: np.ndarray

    def __post_init__(self) -> None:
        for name in ("positions", "normals", "edges"):
            array = np.array(getattr(self, name), dtype=np.float32).reshape(-1, 3)
            if not np.isfinite(array).all():
                raise ValueError(f"Mesh {name} must be finite")
            object.__setattr__(self, name, array)
        if self.positions.shape != self.normals.shape or len(self.positions) % 3 or len(self.edges) % 2:
            raise ValueError("Mesh requires whole triangles, one normal per vertex and edge pairs")

    def bbox(self) -> tuple[Vec, Vec] | None:
        points = np.concatenate((self.positions, self.edges))
        if not len(points):
            return None
        return triple(points.min(axis=0)), triple(points.max(axis=0))


@dataclass
class Shown:
    """One object of the scene. `source` is the build123d shape; it never leaves the run process."""

    name: str
    color: Color
    mesh: Mesh
    volume: float | None = None  # mm³, for solids
    source: Shape | Mesh | None = None
    matrix: Matrix | None = None  # None: the mesh is in world coordinates; else the mesh's placement

    def world(self) -> Mesh:
        """The mesh in world coordinates (exports, reports)."""
        return self.mesh if self.matrix is None else moved(self.mesh, self.matrix)

    def bbox(self) -> tuple[Vec, Vec] | None:
        """The bounds of the placed mesh (of its points, not a turned box: exact for turned parts)."""
        if self.matrix is None:
            return self.mesh.bbox()
        points = np.concatenate((self.mesh.positions, self.mesh.edges))
        if not len(points):
            return None
        m = np.array(self.matrix).reshape(4, 4)
        placed = points @ m[:3, :3].T + m[:3, 3]
        return triple(placed.min(axis=0)), triple(placed.max(axis=0))


def triple(values: Iterable[float]) -> Vec:
    x, y, z = map(float, values)
    return x, y, z


def parse_color(color: object, index: int = 0) -> Color:
    """#RRGGBB, a basic color name, or an RGB triple in 0..1 or 0..255; None picks from the palette."""
    value = PALETTE[index % len(PALETTE)] if color is None else color
    if isinstance(value, str):
        value = NAMED_COLORS.get(value.lower(), value)
        try:
            if len(value) != 7 or value[0] != "#":
                raise ValueError
            return triple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        except ValueError:
            raise ValueError(f"Color must be #RRGGBB or a basic color name, not {color!r}") from None
    rgb = np.asarray(value, dtype=float)
    if rgb.shape != (3,) or not np.isfinite(rgb).all() or rgb.min() < 0 or rgb.max() > 255:
        raise ValueError("Color must be three components in 0..1 or 0..255")
    return triple(rgb / 255 if rgb.max() > 1 else rgb)


def hex_color(color: Color) -> str:
    return "#" + "".join(f"{round(c * 255):02X}" for c in color)


def flatten(objs: object) -> list:
    """Nested lists/tuples of shapes, builders or meshes -> flat list of build123d Shapes and Meshes."""
    import build123d as b
    from build123d.topology import Shape

    if isinstance(objs, (list, tuple)):
        return [item for child in objs for item in flatten(child)]
    if isinstance(objs, Mesh):
        return [objs]
    for builder, attribute in ((b.BuildPart, "part"), (b.BuildSketch, "sketch"), (b.BuildLine, "line")):
        if isinstance(objs, builder):
            objs = getattr(objs, attribute)
            break
    if not isinstance(objs, Shape):
        raise TypeError(f"Cannot show {type(objs).__name__}: expected build123d shapes, builders or meshes")
    if objs.wrapped is None:
        raise ValueError("Cannot show an empty shape")
    return [objs]


def copy_shape(shape: Shape) -> Shape:
    """Copy placement and export metadata, sharing the geometry (build123d's copy() deep-copies it)."""
    from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]
    from build123d.topology import Shape

    reference = Shape.cast(shape.wrapped.Moved(TopLoc_Location()))
    reference.label, reference.color = shape.label, shape.color
    if shape.children:
        wrapped = reference.wrapped
        reference.children = [copy_shape(child) for child in shape.children]
        reference.wrapped = wrapped  # attaching children rebuilds a compound: keep its original placement
    return reference


_placed: dict[int, list[tuple[object, Mesh, float | None]]] = {}  # this run's, by shape without placement


def placed(shape) -> tuple[Mesh, Matrix | None, float | None]:
    """The mesh of a shape in its own coordinates, where the shape is placed and its volume (of its
    solids). Copies moved with Pos/Rot share them: each different shape is computed once per run."""
    if isinstance(shape, Mesh):
        return shape, None, None
    from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]
    from build123d.topology import Shape

    bare = shape.wrapped.Located(TopLoc_Location())
    same = _placed.setdefault(hash(bare), [])
    found = next((entry for entry in same if entry[0].IsEqual(bare)), None)  # pyright: ignore[reportAttributeAccessIssue]
    if found is None:
        found = (bare, tessellate(Shape.cast(bare)), float(shape.volume) if shape.solids() else None)
        same.append(found)
    _, mesh, volume = found
    location = shape.wrapped.Location()
    if location.IsIdentity():
        return mesh, None, volume
    trsf = location.Transformation()
    return mesh, tuple(trsf.Value(i, j) if i < 4 else float(j == 4) for i in range(1, 5) for j in range(1, 5)), volume


def moved(mesh: Mesh, matrix: Matrix) -> Mesh:
    """The mesh placed by the matrix, in world coordinates."""
    m = np.array(matrix).reshape(4, 4)
    rotation, offset = m[:3, :3].T, m[:3, 3]
    return Mesh(mesh.positions @ rotation + offset, mesh.normals @ rotation, mesh.edges @ rotation + offset)


def tessellate(shape, tolerance: float = 0.05, angular_tolerance: float = 0.2) -> Mesh:
    """Triangles and edge polylines of a build123d Shape, in world coordinates."""
    from OCP.BRep import BRep_Tool  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepAdaptor import BRepAdaptor_Curve  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopAbs import TopAbs_REVERSED  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.TopLoc import TopLoc_Location  # pyright: ignore[reportAttributeAccessIssue]

    positions, normals, segments = [], [], []
    faces = shape.faces()
    if faces:
        shape.mesh(tolerance, angular_tolerance)
    for face in faces:
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face.wrapped, location)
        if poly is None:
            continue
        transform = location.Transformation()
        reverse = face.wrapped.Orientation() == TopAbs_REVERSED
        BRepLib_ToolTriangulatedShape.ComputeNormals_s(face.wrapped, poly)
        nodes = range(1, poly.NbNodes() + 1)
        vertices = np.array([poly.Node(i).Transformed(transform).Coord() for i in nodes], dtype=np.float32)
        vertex_normals = np.array([poly.Normal(i).Transformed(transform).Coord() for i in nodes], dtype=np.float32)
        triangles = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=int) - 1
        if reverse:
            triangles = triangles[:, [0, 2, 1]]
            vertex_normals = -vertex_normals
        positions.append(vertices[triangles].reshape(-1, 3))
        normals.append(vertex_normals[triangles].reshape(-1, 3))
    for edge in shape.edges():
        if edge.length <= 1e-12:
            continue
        samples = GCPnts_QuasiUniformDeflection(BRepAdaptor_Curve(edge.wrapped), tolerance)
        if not samples.IsDone():
            raise RuntimeError("Could not discretize an edge")
        points = [samples.Value(i).Coord() for i in range(1, samples.NbPoints() + 1)]
        for a, c in zip(points, points[1:]):
            segments.extend((a, c))
    return Mesh(np.concatenate(positions) if positions else np.empty((0, 3)),
                np.concatenate(normals) if normals else np.empty((0, 3)),
                np.asarray(segments, dtype=np.float32).reshape(-1, 3))


def import_mesh(path, solid: bool = False, max_faces: int = 5000):
    """Read an STL or 3MF file.

    solid=False (default): a fast Mesh you can show() and export, not usable in booleans.
    solid=True: a build123d Solid for booleans; only for small closed meshes (<= max_faces).
    """
    from .files import read_triangles, write_stl

    points = read_triangles(path)
    if not len(points):
        raise ValueError(f"{path}: the mesh has no triangles")
    triangles = points.reshape(-1, 3, 3)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-20)
    mesh = Mesh(points, np.repeat(normals, 3, axis=0), np.empty((0, 3)))
    if not solid:
        return mesh
    if len(triangles) > max_faces:
        raise ValueError(f"{path} has {len(triangles)} faces (max_faces={max_faces}): booleans on big meshes "
                         "are extremely slow. Use solid=False or simplify the mesh.")
    from build123d import Mesher, Solid

    TEMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP) as folder:
        stl = Path(folder) / "mesh.stl"
        write_stl([mesh], stl)
        try:
            shapes = Mesher().read(stl)
        except (AssertionError, RuntimeError, ValueError):
            shapes = []
    if len(shapes) != 1 or not isinstance(shapes[0], Solid) or not shapes[0].is_valid:
        raise ValueError(f"{path} is not a single closed valid solid")
    return shapes[0]


def remove_stale_temp(age: float = 600.0) -> None:
    """Delete temporary folders left behind by runs that were killed (Stop) mid-way."""
    for folder in TEMP.glob("*"):
        try:
            if time.time() - folder.stat().st_mtime > age:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
