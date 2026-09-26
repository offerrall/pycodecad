"""CAD files: export the shown objects (STL, 3MF generic or Bambu Studio, STEP, BREP, GLB) and
read triangle meshes (STL, 3MF).

Exports run where the script ran, so they write the real build123d shapes, not preview triangles.
"""
from __future__ import annotations

import json
import re
import struct
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from .cad import Mesh, Shown, copy_shape, hex_color

if TYPE_CHECKING:
    from build123d.topology import Shape

FORMATS = ("stl", "3mf", "step", "brep", "glb")
PROFILES = ("generic", "bambu")
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"


def export(shown: list[Shown], path: str | Path, profile: str = "generic") -> Path:
    """Write the objects to `path`; the format comes from its extension."""
    path = Path(path)
    kind = path.suffix.lower().lstrip(".")
    if kind not in FORMATS:
        raise ValueError(f"Unknown export format {path.suffix!r}: use one of {', '.join(FORMATS)}")
    if profile not in PROFILES:
        raise ValueError(f"Unknown 3MF profile {profile!r}: use generic or bambu")
    if not shown:
        raise ValueError("Nothing to export: the script shows no objects")
    if kind == "glb":
        path.write_bytes(encode_glb(shown))
    elif any(isinstance(obj.source, Mesh) for obj in shown):
        _export_meshes(shown, path, kind)
    else:
        _export_shapes(shown, path, kind)
    if kind == "3mf" and profile == "bambu":
        adapt_bambu(path)
    return path


def _export_meshes(shown: list[Shown], path: Path, kind: str) -> None:
    """A scene with imported meshes: write triangles (STL/3MF only)."""
    if kind in ("step", "brep"):
        raise ValueError(f"{kind.upper()} cannot hold triangle meshes: export STL, 3MF or GLB, "
                         "or use import_mesh(path, solid=True) for small closed meshes")
    if kind == "stl":
        write_stl([obj.world() for obj in shown], path)
    else:
        write_3mf(shown, path)


def _export_shapes(shown: list[Shown], path: Path, kind: str) -> None:
    import build123d as b

    if kind == "3mf":
        mesher = b.Mesher()
        mesher.add_shape([_labeled(obj) for obj in shown])  # one named, colored 3MF object each
        mesher.write(str(path))
        return
    # Independent wrappers keep the source shapes unparented without copying their geometry.
    sources = [_shape(obj) for obj in shown]
    shape = sources[0] if len(sources) == 1 else b.Compound(children=[copy_shape(s) for s in sources])
    writer = {"stl": b.export_stl, "step": b.export_step, "brep": b.export_brep}[kind]
    if not writer(shape, str(path)):
        raise RuntimeError(f"Could not write {path}")


def _shape(obj: Shown) -> Shape:
    # Without meshes in the scene every source is the shape that show() received.
    assert obj.source is not None and not isinstance(obj.source, Mesh)
    return obj.source


def _labeled(obj: Shown) -> Shape:
    import build123d as b

    # A childless Compound stays one mesh; Mesher would split a compound with children.
    source = _shape(obj)
    shape = b.Compound(source.wrapped) if isinstance(source, b.Compound) else copy_shape(source)
    shape.label = obj.name
    shape.color = b.Color(*obj.color)
    return shape


# --- triangle meshes -------------------------------------------------------------------------

STL_TRIANGLE = np.dtype([("normal", "<f4", (3,)), ("points", "<f4", (3, 3)), ("attribute", "<u2")])


def read_triangles(path) -> np.ndarray:
    """Vertices of an STL (binary or ASCII) or 3MF file, 3 rows per triangle, in millimetres."""
    path = Path(path)
    if path.suffix.lower() == ".stl":
        data = path.read_bytes()
        if len(data) >= 84 and len(data) == 84 + struct.unpack_from("<I", data, 80)[0] * 50:
            return np.frombuffer(data, dtype=STL_TRIANGLE, offset=84)["points"].reshape(-1, 3).copy()
        vertices = re.findall(rb"\bvertex\s+(\S+\s+\S+\s+\S+)", data)
        if not data.lstrip().lower().startswith(b"solid") or not vertices or len(vertices) % 3:
            raise ValueError(f"{path}: not a binary or ASCII STL file")
        return np.array(b" ".join(vertices).split(), dtype=np.float32).reshape(-1, 3)
    if path.suffix.lower() != ".3mf":
        raise ValueError(f"{path}: meshes must be STL or 3MF files")
    from build123d import Mesher

    reader = Mesher()
    assert reader.model is not None  # Mesher() always creates its lib3mf model
    reader.model.QueryReader("3mf").ReadFromFile(str(path))
    model = reader.model.MergeToModel()  # resolves components and their transforms
    meshes, points = model.GetMeshObjects(), []
    while meshes.MoveNext():
        mesh = meshes.GetCurrentMeshObject()
        vertices = np.array([vertex.Coordinates[:] for vertex in mesh.GetVertices()], dtype=np.float32)
        triangles = np.array([triangle.Indices[:] for triangle in mesh.GetTriangleIndices()], dtype=np.int64)
        if triangles.size:
            points.append(vertices[triangles].reshape(-1, 3))
    unit = (0.001, 1.0, 10.0, 25.4, 304.8, 1000.0)[model.GetUnit()]  # lib3mf units, in mm
    return np.concatenate(points) * unit if points else np.empty((0, 3), dtype=np.float32)


def write_stl(meshes: list[Mesh], path) -> None:
    triangles = np.zeros(sum(len(mesh.positions) // 3 for mesh in meshes), dtype=STL_TRIANGLE)
    triangles["points"] = np.concatenate([mesh.positions for mesh in meshes]).reshape(-1, 3, 3)
    triangles["normal"] = np.concatenate([mesh.normals[::3] for mesh in meshes])
    Path(path).write_bytes(b"pycodecad".ljust(80, b"\0") + struct.pack("<I", len(triangles)) + triangles.tobytes())


def write_3mf(shown: list[Shown], path) -> None:
    """A plain 3MF of triangle meshes: one named, colored object per shown object."""
    with ZipFile(path, "w", ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{CONTENT_TYPES}"><Default Extension="rels" '
                         'ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default '
                         'Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                         'relationships"><Relationship Id="rel0" Target="/3D/3dmodel.model" Type="http://schemas.'
                         'microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        with archive.open("3D/3dmodel.model", "w") as model:
            def write(text: str) -> None:
                model.write(text.encode())

            def write_rows(template: str, rows: np.ndarray) -> None:
                for start in range(0, len(rows), 8192):  # format in blocks: fast for big meshes
                    block = rows[start:start + 8192]
                    write((template * len(block)) % tuple(block.ravel().tolist()))

            write(f'<model xmlns="{CORE}" unit="millimeter"><resources><basematerials id="1">')
            for obj in shown:
                write(f'<base name={quoteattr(obj.name)} displaycolor="{hex_color(obj.color)}FF"/>')
            write("</basematerials>")
            for index, obj in enumerate(shown):
                vertices, triangles = np.unique(obj.world().positions, axis=0, return_inverse=True)
                triangles = triangles.reshape(-1, 3)
                # 3MF forbids triangles that repeat a vertex; STL files often have such degenerate ones.
                triangles = triangles[(triangles[:, 0] != triangles[:, 1]) & (triangles[:, 1] != triangles[:, 2])
                                      & (triangles[:, 0] != triangles[:, 2])]
                write(f'<object id="{index + 2}" type="model" name={quoteattr(obj.name)} pid="1" pindex="{index}">'
                      "<mesh><vertices>")
                write_rows('<vertex x="%.9g" y="%.9g" z="%.9g"/>', vertices)
                write("</vertices><triangles>")
                write_rows('<triangle v1="%d" v2="%d" v3="%d"/>', triangles)
                write("</triangles></mesh></object>")
            write("</resources><build>" + "".join(f'<item objectid="{i + 2}"/>' for i in range(len(shown))) + "</build></model>")


# --- Bambu Studio 3MF ----------------------------------------------------------------------

def adapt_bambu(path: Path) -> None:
    """Rewrite colors and object names the way Bambu Studio reads them. Geometry only: no printer
    or filament presets are embedded."""
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    ET.register_namespace("", CORE)
    ET.register_namespace("m", MATERIAL)
    ET.register_namespace("p", "http://schemas.microsoft.com/3dmanufacturing/production/2015/06")
    model = ET.fromstring(entries["3D/3dmodel.model"])
    for materials in model.findall("{*}resources/{*}basematerials"):
        materials.tag = f"{{{MATERIAL}}}colorgroup"
        for color in materials:
            value = color.attrib["displaycolor"]
            color.tag = f"{{{MATERIAL}}}color"
            color.attrib.clear()
            color.set("color", value)
    config = ET.Element("config")
    for obj in model.findall("{*}resources/{*}object"):
        if "name" in obj.attrib:
            item = ET.SubElement(config, "object", id=obj.attrib["id"])
            ET.SubElement(item, "metadata", key="name", value=obj.attrib["name"])
    application = ET.Element(f"{{{CORE}}}metadata", name="Application")
    application.text = "pycodecad"
    model.insert(0, application)
    ET.register_namespace("ct", CONTENT_TYPES)
    types = ET.fromstring(entries["[Content_Types].xml"])
    ET.SubElement(types, f"{{{CONTENT_TYPES}}}Default", Extension="config", ContentType="application/xml")
    entries["3D/3dmodel.model"] = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    entries["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
    entries["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    path.write_bytes(output.getvalue())


# --- GLB (glTF 2.0 binary) -----------------------------------------------------------------

def encode_glb(shown: list[Shown]) -> bytes:
    """The preview triangles and edges, converted from millimetres/Z-up to glTF metres/Y-up."""
    doc: dict[str, Any] = dict(asset=dict(version="2.0", generator="pycodecad"), scene=0, scenes=[dict(nodes=[])],
               nodes=[], meshes=[], materials=[], accessors=[], bufferViews=[], buffers=[])
    binary = bytearray()

    def accessor(values: np.ndarray, normal: bool = False) -> int:
        data = np.asarray(values, dtype="<f4")[:, [0, 2, 1]].copy()
        data[:, 2] *= -1
        if not normal:
            data *= 0.001
        doc["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=data.nbytes, target=34962))
        binary.extend(data.tobytes())
        result = dict(bufferView=len(doc["bufferViews"]) - 1, componentType=5126, count=len(data), type="VEC3")
        if not normal:
            result.update(min=data.min(axis=0).tolist(), max=data.max(axis=0).tolist())
        doc["accessors"].append(result)
        return len(doc["accessors"]) - 1

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    for obj in shown:
        material = len(doc["materials"])
        doc["materials"].append(dict(name=obj.name, doubleSided=True, pbrMetallicRoughness=dict(
            baseColorFactor=[*map(linear, obj.color), 1], metallicFactor=0, roughnessFactor=0.6)))
        primitives = []
        mesh = obj.world()
        if len(mesh.positions):
            attributes = dict(POSITION=accessor(mesh.positions), NORMAL=accessor(mesh.normals, True))
            primitives.append(dict(attributes=attributes, mode=4, material=material))
        if len(mesh.edges):
            primitives.append(dict(attributes=dict(POSITION=accessor(mesh.edges)), mode=1, material=material))
        if primitives:
            doc["meshes"].append(dict(name=obj.name, primitives=primitives))
            doc["nodes"].append(dict(name=obj.name, mesh=len(doc["meshes"]) - 1))
            doc["scenes"][0]["nodes"].append(len(doc["nodes"]) - 1)
    if not binary:
        raise ValueError("Nothing to export: the objects have no geometry")
    doc["buffers"].append(dict(byteLength=len(binary)))
    payload = json.dumps(doc, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(payload) + len(binary))
            + struct.pack("<I4s", len(payload), b"JSON") + payload
            + struct.pack("<I4s", len(binary), b"BIN\0") + bytes(binary))
