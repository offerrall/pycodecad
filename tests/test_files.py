import json
import struct
from zipfile import ZipFile

import numpy as np
import pytest

from conftest import tetrahedron
from pycodecad import cad, runner
from pycodecad.files import read_triangles, write_3mf, write_stl

TWO_PARTS = """from build123d import Box, Pos
from pycodecad import show
show(Box(10, 10, 10), name="a", color="#FF0000")
show(Pos(20, 0, 0) * Box(5, 5, 5), name="b")
"""


def export(tmp_path, name, profile="generic", code=TWO_PARTS):
    target = tmp_path / name
    result = runner.Run(code, str(tmp_path / "part.py"), export=str(target), profile=profile).wait(60)
    assert result.error is None, result.error
    assert result.exported == str(target)
    return target


def test_stl(tmp_path):
    points = read_triangles(export(tmp_path, "out.stl"))
    assert len(points) >= 24 * 3
    assert points.min(axis=0).tolist() == pytest.approx([-5, -5, -5])


@pytest.mark.parametrize("move,extension", [("move", "stl"), ("move", "3mf"), ("locate", "stl")])
def test_export_keeps_each_shown_position_when_the_original_shape_moves(tmp_path, extension, move):
    code = ("from build123d import Box, Pos\nfrom pycodecad import show\n"
            "box = Box(10, 10, 10)\nshow(box, name='before')\n"
            f"box.{move}(Pos(100, 0, 0))\nshow(box, name='after')\n")
    target = tmp_path / f"positions.{extension}"
    result = runner.Run(code, str(tmp_path / "part.py"), export=str(target)).wait(60)
    assert result.error is None, result.error
    assert result.exported == str(target)
    assert [obj.name for obj in result.shown] == ["before", "after"]
    expected = [[[-5, -5, -5], [5, 5, 5]], [[95, -5, -5], [105, 5, 5]]]
    for obj, bounds in zip(result.shown, expected, strict=True):
        box = obj.bbox()
        assert box is not None and np.allclose(box, bounds)
    points = read_triangles(target)
    assert np.allclose(points.min(axis=0), [-5, -5, -5])
    assert np.allclose(points.max(axis=0), [105, 5, 5])


def test_3mf_keeps_names_and_colors(tmp_path):
    with ZipFile(export(tmp_path, "out.3mf")) as archive:
        model = archive.read("3D/3dmodel.model").decode()
    assert 'name="a"' in model and 'name="b"' in model and "#FF0000" in model.upper()


def test_bambu_3mf(tmp_path):
    with ZipFile(export(tmp_path, "out.3mf", "bambu")) as archive:
        config = archive.read("Metadata/model_settings.config").decode()
        model = archive.read("3D/3dmodel.model").decode()
    assert 'value="a"' in config and "colorgroup" in model and "pycodecad" in model


def test_step_and_brep(tmp_path):
    assert "ISO-10303-21" in export(tmp_path, "out.step").read_text()
    assert export(tmp_path, "out.brep").read_text().startswith("DBRep_DrawableShape")


def test_step_keeps_assembly_names_colors_and_placements(tmp_path):
    from build123d import import_step

    code = ("from build123d import Box, Color, Compound, Pos\nfrom pycodecad import show\n"
            "red = Box(10, 10, 10)\nred.label, red.color = 'red_part', Color('red')\n"
            "blue = Pos(20, 0, 0) * Box(4, 4, 4)\n"
            "blue.label, blue.color = 'blue_part', Color('blue')\n"
            "assembly = Compound(label='pair', children=[red, blue])\n"
            "assembly.move(Pos(50, 0, 0))\nshow(assembly)\n"
            "assembly.move(Pos(100, 0, 0))\nred.label = 'edited later'\n"
            "red.color = Color('green')\n")
    assembly = import_step(export(tmp_path, "assembly.step", code=code))
    assert assembly.label == "pair"
    red, blue = [part for part in assembly.descendants if not part.children]
    assert [red.label, blue.label] == ["red_part", "blue_part"]
    assert red.color is not None and blue.color is not None
    assert tuple(red.color) == pytest.approx((1, 0, 0, 1))
    assert tuple(blue.color) == pytest.approx((0, 0, 1, 1))
    box = assembly.bounding_box()
    assert tuple(box.min) == pytest.approx((45, -5, -5))
    assert tuple(box.max) == pytest.approx((72, 5, 5))


def test_glb(tmp_path):
    data = export(tmp_path, "out.glb").read_bytes()
    magic, version, length = struct.unpack("<III", data[:12])
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    size = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + size])
    assert [node["name"] for node in doc["nodes"]] == ["a", "b"]


def test_meshes_export_as_triangles_only(tmp_path):
    (tmp_path / "ref.stl").write_bytes(export(tmp_path, "ref.stl").read_bytes())
    code = "from pycodecad import import_mesh, show\nshow(import_mesh('ref.stl'), name='ref')\n"
    assert len(read_triangles(export(tmp_path, "copy.stl", code=code))) == len(read_triangles(tmp_path / "ref.stl"))
    assert len(read_triangles(export(tmp_path, "copy.3mf", code=code))) > 0
    result = runner.Run(code, str(tmp_path / "part.py"), export=str(tmp_path / "x.step")).wait(60)
    assert "STEP cannot hold triangle meshes" in (result.error or "")


def test_unknown_format_and_empty_scene(tmp_path):
    result = runner.Run(TWO_PARTS, "<editor>", export=str(tmp_path / "out.obj")).wait(60)
    assert "Unknown export format" in (result.error or "")
    result = runner.Run("x = 1", "<editor>", export=str(tmp_path / "out.stl")).wait(60)
    assert result.error is None and result.exported is None and not (tmp_path / "out.stl").exists()


TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)


def test_binary_and_ascii_stl(tmp_path):
    binary = tmp_path / "t.stl"
    write_stl([tetrahedron()], binary)
    assert read_triangles(binary).shape == (12, 3)
    ascii_stl = tmp_path / "a.stl"
    ascii_stl.write_text("solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
                         "endloop\nendfacet\nendsolid t\n")
    assert read_triangles(ascii_stl).tolist() == TRIANGLE.tolist()
    (tmp_path / "bad.stl").write_text("nonsense")
    with pytest.raises(ValueError):
        read_triangles(tmp_path / "bad.stl")


def test_3mf_roundtrip(tmp_path):
    target = tmp_path / "t.3mf"
    write_3mf([cad.Shown("tetra", (1.0, 0.5, 0.0), tetrahedron())], target)
    assert read_triangles(target).shape == (12, 3)


def test_import_mesh_as_mesh_and_as_solid(tmp_path):
    path = tmp_path / "t.stl"
    write_stl([tetrahedron()], path)
    mesh = cad.import_mesh(path)
    assert isinstance(mesh, cad.Mesh) and mesh.bbox() == ((0, 0, 0), (10, 10, 10))
    solid = cad.import_mesh(path, solid=True)
    assert not isinstance(solid, cad.Mesh) and solid.volume == pytest.approx(1000 / 6)
    with pytest.raises(ValueError, match="max_faces"):
        cad.import_mesh(path, solid=True, max_faces=2)


def test_colors():
    assert cad.parse_color("#FF8000") == (1.0, 128 / 255, 0.0)
    assert cad.parse_color("red") == (1.0, 0.0, 0.0)
    assert cad.parse_color((255, 0, 0)) == (1.0, 0.0, 0.0)
    assert cad.parse_color(None, 1) == cad.parse_color(cad.PALETTE[1])
    with pytest.raises(ValueError):
        cad.parse_color("reddish")
