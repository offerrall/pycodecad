"""Dear ImGui (slimgui) on a GLFW window, rendered with ModernGL: input callbacks, textures, drawing."""
from __future__ import annotations

import ctypes
import math
import struct
from typing import Any, cast

import glfw
import moderngl
from slimgui import imgui

from .icons import font_data

VERTEX_SHADER = """#version 330 core
uniform mat4 projection;
in vec2 position; in vec2 uv; in vec4 color;
out vec2 frag_uv; out vec4 frag_color;
void main() {
    frag_uv = uv; frag_color = color / 255.0;
    gl_Position = projection * vec4(position, 0.0, 1.0);
}
"""
FRAGMENT_SHADER = """#version 330 core
uniform sampler2D image_texture;
in vec2 frag_uv; in vec4 frag_color;
out vec4 out_color;
void main() { out_color = frag_color * texture(image_texture, frag_uv); }
"""


class ImguiBackend:
    """Owns the ImGui context. Call new_frame(), build the UI, then render(); shutdown() before GLFW."""

    def __init__(self, window, ctx: moderngl.Context):
        self.window, self.ctx = window, ctx
        self.context = imgui.create_context()
        self.io = imgui.get_io()
        self.io.ini_filename = None
        self.io.backend_flags |= (imgui.BackendFlags.RENDERER_HAS_TEXTURES | imgui.BackendFlags.RENDERER_HAS_VTX_OFFSET
                                  | imgui.BackendFlags.HAS_MOUSE_CURSORS)
        load_fonts(self.io)
        platform = imgui.get_platform_io()
        platform.renderer_texture_max_width = platform.renderer_texture_max_height = ctx.info["GL_MAX_TEXTURE_SIZE"]
        self.program = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
        cast(moderngl.Uniform, self.program["image_texture"]).value = 0
        self.vbo = ctx.buffer(reserve=4096, dynamic=True)
        self.ibo = ctx.buffer(reserve=4096, dynamic=True)
        self.vao = ctx.vertex_array(self.program, [(self.vbo, "2f 2f 4u1", "position", "uv", "color")],
                                    self.ibo, index_element_size=imgui.INDEX_SIZE)
        # ImGui texture ids are OpenGL texture names (as in Dear ImGui's own OpenGL backend): GL name ->
        # the texture, or a moderngl handle made for a name drawn with imgui.image() (e.g. a Viewer's).
        self.textures: dict[int, moderngl.Texture] = {}
        self.font_textures: set[int] = set()  # the ones ImGui created (and we must release)
        # Typed text (str) and key presses ((glfw key, mods, repeat)) since the last input_events(),
        # in arrival order: the code editor applies them in that order.
        self.events: list = []
        self.copying = False  # Ctrl+C/X was pressed: hand what ImGui copies to the system clipboard
        self.last_time: float | None = None
        self.cursors = {kind: glfw.create_standard_cursor(shape) for kind, shape in (
            (imgui.MouseCursor.ARROW, glfw.ARROW_CURSOR), (imgui.MouseCursor.TEXT_INPUT, glfw.IBEAM_CURSOR),
            (imgui.MouseCursor.RESIZE_EW, glfw.HRESIZE_CURSOR), (imgui.MouseCursor.RESIZE_NS, glfw.VRESIZE_CURSOR),
            (imgui.MouseCursor.HAND, glfw.HAND_CURSOR))}
        # The window's input callbacks, and the ones they replace (shutdown() puts those back).
        installed = (
            (glfw.set_key_callback, self._key), (glfw.set_char_callback, self._char),
            (glfw.set_cursor_pos_callback, lambda w, x, y: self.io.add_mouse_pos_event(x, y)),
            (glfw.set_mouse_button_callback, self._mouse_button),
            (glfw.set_scroll_callback, lambda w, x, y: self.io.add_mouse_wheel_event(x, y)),
            (glfw.set_window_focus_callback, lambda w, focused: self.io.add_focus_event(bool(focused))),
            (glfw.set_cursor_enter_callback, self._mouse_enter))
        # Any: glfw's stubs type each setter apart (and refuse None, which puts no callback)
        self.callbacks: list[tuple[Any, Any]] = [(setter, setter(window, callback))
                                                 for setter, callback in cast(Any, installed)]

    # --- input -----------------------------------------------------------------------------

    def _modifiers(self, mods: int) -> None:
        for flag, key in ((glfw.MOD_CONTROL, imgui.Key.MOD_CTRL), (glfw.MOD_SHIFT, imgui.Key.MOD_SHIFT),
                          (glfw.MOD_ALT, imgui.Key.MOD_ALT), (glfw.MOD_SUPER, imgui.Key.MOD_SUPER)):
            self.io.add_key_event(key, bool(mods & flag))

    def _key(self, window, key: int, scancode: int, action: int, mods: int) -> None:
        # ImGui text fields (Save as) use their own clipboard: bridge it to the system one.
        ctrl, shift = mods & glfw.MOD_CONTROL, mods & glfw.MOD_SHIFT
        if action == glfw.PRESS and ((ctrl and key == glfw.KEY_V) or (shift and key == glfw.KEY_INSERT)):
            imgui.set_clipboard_text(clipboard_text())
        if action == glfw.PRESS and ((ctrl and key in (glfw.KEY_C, glfw.KEY_X, glfw.KEY_INSERT))
                                     or (shift and key == glfw.KEY_DELETE)):
            imgui.set_clipboard_text("")
            self.copying = True
        if action in (glfw.PRESS, glfw.REPEAT):
            self.events.append((key, mods, action == glfw.REPEAT))
        if action not in (glfw.PRESS, glfw.RELEASE):
            return
        self._modifiers(mods)
        mapped = imgui_key(key)
        if mapped is not None:
            self.io.add_key_event(mapped, action == glfw.PRESS)

    def _char(self, window, codepoint: int) -> None:
        if 0 < codepoint <= 0x10FFFF:
            self.io.add_input_character(codepoint)
            if chr(codepoint).isprintable():
                self.events.append(chr(codepoint))

    def _mouse_button(self, window, button: int, action: int, mods: int) -> None:
        self._modifiers(mods)
        if 0 <= button < 5:
            self.io.add_mouse_button_event(button, action == glfw.PRESS)

    def _mouse_enter(self, window, entered: int) -> None:
        position = glfw.get_cursor_pos(window) if entered else (-3.4e38, -3.4e38)
        self.io.add_mouse_pos_event(*position)

    def input_events(self) -> list:
        """Typed text and key presses since the last call, in order (see self.events)."""
        events, self.events = self.events, []
        return events

    # --- frames ----------------------------------------------------------------------------

    def new_frame(self) -> None:
        width, height = glfw.get_window_size(self.window)
        fb_width, fb_height = glfw.get_framebuffer_size(self.window)
        self.io.display_size = width, height
        self.io.display_framebuffer_scale = (fb_width / width if width else 1.0, fb_height / height if height else 1.0)
        now = glfw.get_time()
        self.io.delta_time = max(now - self.last_time, 1e-6) if self.last_time is not None else 1 / 60
        self.last_time = now
        cursor = imgui.get_mouse_cursor()
        glfw.set_cursor(self.window, self.cursors.get(cursor, self.cursors[imgui.MouseCursor.ARROW]))
        imgui.new_frame()

    def texture(self, name: int) -> moderngl.Texture:
        """The texture of a GL name, to bind it (a handle of any size binds the same texture)."""
        if name not in self.textures:
            self.textures[name] = self.ctx.external_texture(name, (1, 1), 4, 0, "f1")
        return self.textures[name]

    def _update_texture(self, data) -> None:
        """ImGui 1.92 creates and updates its font atlas through the renderer."""
        if data.status == imgui.TextureStatus.WANT_CREATE:
            texture = self.ctx.texture((data.width, data.height), data.bytes_per_pixel, data.get_pixels(), alignment=1)
            texture.filter = moderngl.LINEAR, moderngl.LINEAR
            if data.format == imgui.TextureFormat.ALPHA8:
                texture.swizzle = "111R"
            self.textures[texture.glo] = texture
            self.font_textures.add(texture.glo)
            data.set_tex_id(texture.glo)
            data.set_status(imgui.TextureStatus.OK)
        elif data.status == imgui.TextureStatus.WANT_UPDATES:
            texture = self.textures[data.get_tex_id()]
            pixels = data.get_pixels().reshape(data.height, data.width, data.bytes_per_pixel)
            for rect in data.updates:
                block = pixels[rect.y:rect.y + rect.h, rect.x:rect.x + rect.w].tobytes()
                texture.write(block, viewport=(rect.x, rect.y, rect.w, rect.h), alignment=1)
            data.set_status(imgui.TextureStatus.OK)
        elif data.status == imgui.TextureStatus.WANT_DESTROY and data.unused_frames > 0:
            texture_id = data.get_tex_id()
            if texture_id in self.font_textures:
                self.font_textures.discard(texture_id)
                self.textures.pop(texture_id).release()
            data.set_tex_id(0)
            data.set_status(imgui.TextureStatus.DESTROYED)

    def render(self) -> None:
        """Finish the ImGui frame and draw it into the current framebuffer."""
        imgui.render()
        copied = imgui.get_clipboard_text() if self.copying else None
        if copied:  # copied or cut in an ImGui text field
            glfw.set_clipboard_string(None, copied)  # pyright: ignore[reportArgumentType]  # glfw ignores the window
            self.copying = False
        data = imgui.get_draw_data()
        for texture in data.textures or ():
            self._update_texture(texture)
        scale_x, scale_y = data.framebuffer_scale
        width, height = int(self.io.display_size[0] * scale_x), int(self.io.display_size[1] * scale_y)
        if width <= 0 or height <= 0:
            return
        ctx = self.ctx
        ctx.enable_only(moderngl.BLEND)
        # rgb and alpha blended separately: moderngl takes 4 values, its stub only 2
        ctx.blend_func = (  # pyright: ignore[reportAttributeAccessIssue]
            moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
        ctx.viewport = (0, 0, width, height)
        w, h = self.io.display_size
        projection = struct.pack("16f", 2 / w, 0, 0, 0, 0, -2 / h, 0, 0, 0, 0, -1, 0, -1, 1, 0, 1)
        cast(moderngl.Uniform, self.program["projection"]).write(projection)
        for drawlist in data.commands_lists:
            for buffer, pointer, size in (
                (self.vbo, drawlist.vtx_buffer_data, drawlist.vtx_buffer_size * imgui.VERTEX_SIZE),
                (self.ibo, drawlist.idx_buffer_data, drawlist.idx_buffer_size * imgui.INDEX_SIZE),
            ):
                if size:
                    buffer.orphan(max(buffer.size, 1 << (size - 1).bit_length()))
                    buffer.write(ctypes.string_at(pointer, size))
            for command in drawlist.commands:
                if not command.elem_count:
                    continue
                x0, y0, x1, y1 = command.clip_rect
                left, top = max(0, math.floor(x0 * scale_x)), max(0, math.floor(y0 * scale_y))
                right, bottom = min(width, math.ceil(x1 * scale_x)), min(height, math.ceil(y1 * scale_y))
                if right <= left or bottom <= top:
                    continue
                ctx.scissor = left, height - bottom, right - left, bottom - top
                self.texture(command.tex_ref.get_tex_id()).use(0)
                base = command.vtx_offset * imgui.VERTEX_SIZE
                # Vertex offsets: rebind the attributes at the command's first vertex.
                for name, fmt, field in (("position", "2f", imgui.VERTEX_BUFFER_POS_OFFSET),
                                         ("uv", "2f", imgui.VERTEX_BUFFER_UV_OFFSET),
                                         ("color", "4u1", imgui.VERTEX_BUFFER_COL_OFFSET)):
                    self.vao.bind(cast(moderngl.Attribute, self.program[name]).location, "f", self.vbo, fmt,
                                  offset=base + field, stride=imgui.VERTEX_SIZE)
                self.vao.render(moderngl.TRIANGLES, vertices=command.elem_count, first=command.idx_offset)
        ctx.scissor = None

    def shutdown(self) -> None:
        for setter, previous in self.callbacks:  # no input may reach the destroyed ImGui context
            setter(self.window, previous)
        for texture_id in self.font_textures:
            self.textures[texture_id].release()
        for resource in (self.vao, self.ibo, self.vbo, self.program):
            resource.release()
        for cursor in self.cursors.values():
            glfw.destroy_cursor(cursor)
        imgui.destroy_context(self.context)


FONT_SIZE = 13.0  # ImGui's built-in font, drawn at its native size


def load_fonts(io) -> None:
    """ImGui's default font with the Lucide icons merged in (see pycodecad.icons), centred on the text."""
    base = imgui.FontConfig()
    base.size_pixels = FONT_SIZE  # explicit, so the icons can merge in at the same size
    io.fonts.add_font_default(base)
    config = imgui.FontConfig()
    config.merge_mode = True
    config.pixel_snap_h = True
    config.glyph_offset = ICON_OFFSET
    io.fonts.add_font_from_memory_ttf(font_data(), FONT_SIZE, config)


ICON_OFFSET = (-2.0, 3.5)


def clipboard_text() -> str:
    text = glfw.get_clipboard_string(None) or b""  # pyright: ignore[reportArgumentType]  # glfw ignores the window
    return text.decode("utf-8", "replace") if isinstance(text, bytes) else text


def imgui_key(key: int):
    """GLFW key code -> imgui.Key (None for keys ImGui does not know)."""
    for first, last, target in ((glfw.KEY_A, glfw.KEY_Z, imgui.Key.KEY_A), (glfw.KEY_0, glfw.KEY_9, imgui.Key.KEY_0),
                                (glfw.KEY_F1, glfw.KEY_F12, imgui.Key.KEY_F1),
                                (glfw.KEY_KP_0, glfw.KEY_KP_EQUAL, imgui.Key.KEY_KEYPAD0)):
        if first <= key <= last:
            return imgui.Key(int(target) + key - first)
    name = KEY_NAMES.get(key)
    return getattr(imgui.Key, "KEY_" + name) if name else None


KEY_NAMES = {getattr(glfw, "KEY_" + name): name for name in (
    "TAB", "PAGE_UP", "PAGE_DOWN", "HOME", "END", "INSERT", "DELETE", "BACKSPACE", "SPACE", "ENTER", "ESCAPE",
    "APOSTROPHE", "COMMA", "MINUS", "PERIOD", "SLASH", "SEMICOLON", "EQUAL", "LEFT_BRACKET", "BACKSLASH",
    "RIGHT_BRACKET", "GRAVE_ACCENT", "LEFT_SHIFT", "LEFT_ALT", "LEFT_SUPER", "RIGHT_SHIFT", "RIGHT_ALT", "RIGHT_SUPER")}
KEY_NAMES.update({glfw.KEY_LEFT: "LEFT_ARROW", glfw.KEY_RIGHT: "RIGHT_ARROW", glfw.KEY_UP: "UP_ARROW",
                  glfw.KEY_DOWN: "DOWN_ARROW", glfw.KEY_LEFT_CONTROL: "LEFT_CTRL", glfw.KEY_RIGHT_CONTROL: "RIGHT_CTRL"})
