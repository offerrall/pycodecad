"""The 3D view: draws meshes, edges, a grid and axes into an off-screen texture with ModernGL."""
from __future__ import annotations

import math
import struct
import zlib
from typing import cast

import moderngl
import numpy as np
from pytypehint import immutable

from . import camera as cam
from .cad import Color, Matrix, Mesh, Shown
from .camera import Camera


@immutable
class Display:
    edges: bool = True
    grid: bool = True
    axes: bool = True


_MESH_VERTEX = '''#version 330
uniform mat4 view; uniform mat4 projection;
in vec3 position; in vec3 normal;
out vec3 n; out vec3 eye;
void main() { vec4 p = view * vec4(position, 1); eye = -p.xyz;
 n = mat3(view) * normal; gl_Position = projection * p; }
'''
_MESH_FRAGMENT = '''#version 330
uniform vec3 color;
in vec3 n; in vec3 eye; out vec4 frag;
void main() {
 vec3 N = normalize(n); if (!gl_FrontFacing) N = -N;
 vec3 V = normalize(eye); vec3 L = normalize(vec3(-0.35, 0.65, 1));
 float diffuse = max(dot(N,L),0.0);
 float hemi = 0.5 + 0.5 * N.y;
 float rim = pow(1.0 - max(dot(N,V),0.0), 3.0);
 float spec = pow(max(dot(N,normalize(L+V)),0.0),48.0);
 frag = vec4(color * (0.49 + 0.42*diffuse + 0.12*hemi) + vec3(0.075)*rim + vec3(0.14)*spec,1);
}
'''
_LINE_VERTEX = '''#version 330
uniform mat4 mvp; uniform float bias;
in vec3 position; out vec3 world;
void main() { world = position; gl_Position = mvp * vec4(position,1);
 gl_Position.z -= bias * gl_Position.w; }
'''
_LINE_FRAGMENT = '''#version 330
uniform vec4 color; uniform float fade; uniform vec2 center;
in vec3 world; out vec4 frag;
void main() { float a = fade > 0.0 ? exp(-pow(length(world.xy-center)/fade,2.0)) : 1.0;
 frag = vec4(color.rgb,color.a*a); }
'''
_BG_VERTEX = '''#version 330
out vec2 uv;
void main() { vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
 uv = p; gl_Position = vec4(p*2.0-1.0, 0, 1); }
'''
_BG_FRAGMENT = '''#version 330
in vec2 uv; out vec4 frag;
void main() { vec3 c = mix(vec3(0.075,0.091,0.12), vec3(0.16,0.19,0.24),uv.y);
 c += 0.012 * (1.0-length(uv-vec2(0.5)));
 frag = vec4(c,1); }
'''


_Frame = tuple[moderngl.Framebuffer, moderngl.Framebuffer, moderngl.Texture]


def _set_uniforms(program: moderngl.Program, **values: object) -> None:
    """Set a program's uniforms in order: bytes are written raw (matrices), anything else is the value."""
    for name, value in values.items():
        uniform = cast(moderngl.Uniform, program[name])  # our shaders' names are all plain uniforms
        if isinstance(value, bytes):
            uniform.write(value)
        else:
            uniform.value = value


Uploaded = tuple[moderngl.VertexArray | None, moderngl.VertexArray | None, list[moderngl.Buffer]]


class Renderer:
    """Draws the scene into its own texture (4x multisampled when the GPU allows)."""

    def __init__(self, ctx: moderngl.Context) -> None:
        self.ctx = ctx
        self._mesh_program = ctx.program(vertex_shader=_MESH_VERTEX, fragment_shader=_MESH_FRAGMENT)
        self._line_program = ctx.program(vertex_shader=_LINE_VERTEX, fragment_shader=_LINE_FRAGMENT)
        self._bg_program = ctx.program(vertex_shader=_BG_VERTEX, fragment_shader=_BG_FRAGMENT)
        self._bg = ctx.vertex_array(self._bg_program, [])
        self._objects: list[tuple[Color, np.ndarray | None, Uploaded]] = []  # color, placement, mesh
        self._uploaded: dict[int, tuple[Mesh, Uploaded]] = {}  # by id of the mesh: kept while drawn
        self._targets: list = []  # texture and framebuffers of the current size
        self._size = (0, 0)
        # (multisampled framebuffer, resolve framebuffer, its texture) of the current size
        self._frame: _Frame | None = None
        self._grid_key: tuple | None = None
        self._grid: tuple[moderngl.VertexArray, moderngl.Buffer] | None = None  # the grid lines
        axis = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0], [0, 0, 0], [0, 0, 1]], dtype="f4")
        self._axis_buffer = ctx.buffer(axis.tobytes())
        self._axis_vao = ctx.vertex_array(self._line_program, [(self._axis_buffer, "3f", "position")])

    def set_meshes(self, meshes: list[tuple[Color, Mesh, Matrix | None]]) -> None:
        """Replace what is drawn: (color, mesh, placement) items. A mesh drawn before
        (the same object, e.g. in every frame of an animation) is not uploaded again."""
        kept: dict[int, tuple[Mesh, Uploaded]] = {}
        self._objects = []
        for color, mesh, matrix in meshes:
            key = id(mesh)
            if key not in kept:
                kept[key] = self._uploaded.pop(key, None) or (mesh, self._upload(mesh))
            placement = None if matrix is None else np.array(matrix, dtype="f4").reshape(4, 4)
            self._objects.append((color, placement, kept[key][1]))
        for _, (triangles, edges, buffers) in self._uploaded.values():
            for resource in (triangles, edges, *buffers):
                if resource is not None:
                    resource.release()
        self._uploaded = kept

    def _upload(self, mesh: Mesh) -> Uploaded:
        triangles = edges = None
        buffers = []
        if len(mesh.positions):
            buffers.append(self.ctx.buffer(np.column_stack((mesh.positions, mesh.normals)).tobytes()))
            triangles = self.ctx.vertex_array(self._mesh_program, [(buffers[-1], "3f 3f", "position", "normal")])
        if len(mesh.edges):
            buffers.append(self.ctx.buffer(mesh.edges.tobytes()))
            edges = self.ctx.vertex_array(self._line_program, [(buffers[-1], "3f", "position")])
        return triangles, edges, buffers

    def _resize(self, width: int, height: int) -> _Frame:
        if self._frame is None or self._size != (width, height):
            for target in reversed(self._targets):
                target.release()
            ctx = self.ctx
            samples = 4 if ctx.max_samples >= 4 else 0
            texture = ctx.texture((width, height), 4)
            texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            resolve = ctx.framebuffer(color_attachments=[texture])
            color = ctx.renderbuffer((width, height), 4, samples=samples)
            depth = ctx.depth_renderbuffer((width, height), samples=samples)
            fbo = ctx.framebuffer([color], depth)
            self._frame = fbo, resolve, texture
            self._targets = [texture, resolve, color, depth, fbo]
            self._size = width, height
        return self._frame

    def _draw_grid(self, fbo: moderngl.Framebuffer, mvp: np.ndarray, camera: Camera) -> None:
        desired = max(camera.distance / 18, 1e-9)
        magnitude = 10 ** math.floor(math.log10(desired))
        spacing = next(step * magnitude for step in (1, 2, 5, 10) if step * magnitude >= desired)
        center = np.round(np.asarray(camera.target[:2]) / spacing) * spacing
        key = (spacing, *center)
        extent = spacing * 60
        if self._grid is None or key != self._grid_key:  # rebuild the lines only when spacing or center change
            for resource in self._grid or ():
                resource.release()
            points = []
            for i in range(-60, 61):
                p = i * spacing
                points.extend([(center[0]+p, center[1]-extent, 0), (center[0]+p, center[1]+extent, 0),
                               (center[0]-extent, center[1]+p, 0), (center[0]+extent, center[1]+p, 0)])
            buffer = self.ctx.buffer(np.asarray(points, dtype='f4').tobytes())
            self._grid = self.ctx.vertex_array(self._line_program, [(buffer, '3f', 'position')]), buffer
            self._grid_key = key
        _set_uniforms(self._line_program, mvp=mvp.tobytes(), bias=0.0, fade=camera.distance * 0.65,
                      center=tuple(camera.target[:2]), color=(0.40, 0.47, 0.56, 0.22))
        fbo.depth_mask = False
        self._grid[0].render(moderngl.LINES)
        fbo.depth_mask = True

    def draw(self, camera: Camera, display: Display, width: int, height: int) -> moderngl.Texture:
        width, height = max(1, int(width)), max(1, int(height))
        fbo, resolve, texture = self._resize(width, height)
        ctx = self.ctx
        fbo.use()
        ctx.viewport = (0, 0, width, height)
        ctx.scissor = None
        ctx.wireframe = False
        fbo.depth_mask = True
        ctx.enable_only(moderngl.NOTHING)
        fbo.clear(0, 0, 0, 1, depth=1)
        self._bg.render(moderngl.TRIANGLES, vertices=3)
        # Column-major tuples read row-major give the transposes this renderer works with.
        view, projection = (np.array(m, dtype='f4').reshape(4, 4)
                            for m in cam.matrices(camera, width / height))
        mvp = np.ascontiguousarray(view @ projection)
        _set_uniforms(self._mesh_program, view=view.tobytes(), projection=projection.tobytes())
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = '<='
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        ctx.line_width = 1.0
        if display.grid:
            self._draw_grid(fbo, mvp, camera)
        for color, placement, (triangles, _, _) in self._objects:
            if triangles is not None:
                placed = view if placement is None else np.ascontiguousarray(placement.T @ view)
                _set_uniforms(self._mesh_program, view=placed.tobytes(), color=color)
                triangles.render(moderngl.TRIANGLES)
        p = self._line_program
        _set_uniforms(p, mvp=mvp.tobytes(), fade=0.0, bias=0.000015, color=(0.065, 0.055, 0.045, 0.85))
        if display.edges:
            for _, placement, (_, edges, _) in self._objects:
                if edges is not None:
                    placed = mvp if placement is None else np.ascontiguousarray(placement.T @ mvp)
                    _set_uniforms(p, mvp=placed.tobytes())
                    edges.render(moderngl.LINES)
        if display.axes:
            ctx.disable(moderngl.DEPTH_TEST)
            size = min(100, width, height)
            ctx.viewport = (8, 8, size, size)
            matrix = np.eye(4, dtype='f4')
            matrix[:3, :3] = view.T[:3, :3] * 0.66
            matrix[:2, 3] = -0.12
            _set_uniforms(p, mvp=np.ascontiguousarray(matrix.T).tobytes(), bias=0.0)
            ctx.line_width = min(2.0, ctx.info.get('GL_ALIASED_LINE_WIDTH_RANGE', (1, 1))[1])
            for i, color in enumerate(((0.95,0.32,0.29,1), (0.4,0.85,0.48,1), (0.35,0.63,1,1))):
                _set_uniforms(p, color=color)
                self._axis_vao.render(moderngl.LINES, vertices=2, first=i*2)
        ctx.viewport = (0, 0, width, height)
        ctx.line_width = 1.0
        ctx.copy_framebuffer(resolve, fbo)
        return texture

    def read_image(self) -> np.ndarray:
        """The last drawn frame as a top-down (height, width, 4) uint8 array."""
        assert self._frame is not None, "draw() first"
        width, height = self._size
        pixels = np.frombuffer(self._frame[2].read(alignment=1), dtype=np.uint8).reshape(height, width, 4)
        return np.flipud(pixels)

    def release(self) -> None:
        """Free the GL resources (while the context is still current)."""
        self.set_meshes([])
        for resource in (*(self._grid or ()), self._axis_vao, self._axis_buffer, self._bg,
                         self._mesh_program, self._line_program, self._bg_program, *reversed(self._targets)):
            resource.release()


# --- off-screen pictures (the CLI `render` command) -------------------------

MAX_SIZE = 8192  # pixels per side of each view


def check_size(size: tuple[int, int]) -> None:
    if len(size) != 2 or not all(isinstance(side, int) and 1 <= side <= MAX_SIZE for side in size):
        raise ValueError(f"Image size must be two whole numbers of pixels in 1..{MAX_SIZE}, not {size!r}")


def render_views(shown: list[Shown], views: list[str | Camera], size: tuple[int, int]) -> np.ndarray:
    """One image per view (a name like "iso", or a Camera), side by side in a labeled grid when
    there are several. Needs no window: uses an off-screen GL context."""
    check_size(size)
    width, height = size
    ctx = moderngl.create_standalone_context()
    renderer = Renderer(ctx)
    try:
        renderer.set_meshes([(obj.color, obj.mesh, obj.matrix) for obj in shown])
        bbox = cam.scene_bbox([obj.bbox() for obj in shown])
        images = []
        for view in views:
            if isinstance(view, str):
                camera = cam.set_view(Camera(), view)
                camera = cam.fit(camera, bbox) if bbox else camera
            else:
                camera = view
            renderer.draw(camera, Display(), width, height)
            image = renderer.read_image().copy()
            if len(views) > 1:
                draw_label(image, view if isinstance(view, str) else "window")
            images.append(image)
    finally:
        renderer.release()
        ctx.release()
    columns = 1 if len(images) == 1 else 2
    rows = -(-len(images) // columns)
    grid = np.zeros((rows * height, columns * width, 4), dtype=np.uint8)
    grid[..., 3] = 255
    for index, image in enumerate(images):
        row, column = divmod(index, columns)
        grid[row * height:(row + 1) * height, column * width:(column + 1) * width] = image
    return grid


def png_bytes(image: np.ndarray) -> bytes:
    """PNG file of a top-down (height, width, 3 or 4) uint8 image."""
    height, width, channels = image.shape
    rows = b"".join(b"\0" + image[y].tobytes() for y in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack("!I", len(payload)) + kind + payload + struct.pack("!I", zlib.crc32(kind + payload))

    header = struct.pack("!2I5B", width, height, 8, 6 if channels == 4 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


# A 5x7 pixel font for the view names in render grids.
GLYPHS = dict(
    A="01110100011000111111100011000110001", B="11110100011000111110100011000111110",
    C="01110100011000010000100001000101110", D="11110100011000110001100011000111110",
    E="11111100001000011110100001000011111", F="11111100001000011110100001000010000",
    G="01110100011000010111100011000101111", H="10001100011000111111100011000110001",
    I="01110001000010000100001000010001110", K="10001100101010011000101001001010001",
    L="10000100001000010000100001000011111", M="10001110111010110101100011000110001",
    N="10001110011010110011100011000110001", O="01110100011000110001100011000101110",
    P="11110100011000111110100001000010000", R="11110100011000111110101001001010001",
    S="01111100001000001110000010000111110", T="11111001000010000100001000010000100",
    W="10001100011000110101101011010101010",
)


def draw_label(image: np.ndarray, text: str, scale: int = 3) -> None:
    """Write uppercase text in the top-left corner of the image, in place."""
    x = y = 12
    for char in text.upper():
        glyph = GLYPHS.get(char)
        if glyph:
            pixels = np.array([int(bit) for bit in glyph], dtype=bool).reshape(7, 5)
            block = np.kron(pixels, np.ones((scale, scale), dtype=bool))
            region = image[y:y + block.shape[0], x:x + block.shape[1]]
            region[block[:region.shape[0], :region.shape[1]]] = (235, 238, 245, 255)
        x += 6 * scale
