"""The code editor widget: Python highlighting and keyboard/mouse editing, drawn with ImGui."""
from __future__ import annotations

import builtins
import io
import keyword
import tokenize
from dataclasses import replace
from functools import lru_cache

import glfw
from slimgui import imgui

from . import textedit
from .imgui_backend import clipboard_text
from .textedit import Editor

COLORS = {
    "text": (0.84, 0.87, 0.91, 1.0),
    "keyword": (0.79, 0.57, 0.95, 1.0),
    "builtin": (0.42, 0.77, 0.96, 1.0),
    "string": (0.66, 0.82, 0.52, 1.0),
    "number": (0.96, 0.71, 0.42, 1.0),
    "comment": (0.48, 0.59, 0.65, 1.0),
    "decorator": (0.95, 0.78, 0.42, 1.0),
    "definition": (0.98, 0.85, 0.56, 1.0),
    "cad": (0.32, 0.84, 0.75, 1.0),
}
CAD_NAMES = frozenset("""
Box Cylinder Sphere Cone Torus Wedge BuildPart BuildSketch BuildLine
Part Sketch Solid Face Wire Edge Vertex Compound Location Locations
PolarLocations GridLocations HexLocations Plane Axis Vector Color
Align Mode GeomType Rectangle RectangleRounded Circle Ellipse Polygon
RegularPolygon Polyline Line Spline Bezier RadiusArc CenterArc ThreePointArc
fillet chamfer extrude revolve loft sweep offset mirror scale split
make_face make_hull add subtract intersect Pos Rot show clear import_mesh render
""".split())
BUILTINS = frozenset(dir(builtins))
SELECTION = (0.25, 0.48, 0.78, 0.45)
CURRENT_LINE = (0.8, 0.85, 1.0, 0.045)
ERROR_LINE = (0.8, 0.2, 0.2, 0.23)


@lru_cache(maxsize=16)
def highlight(text: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Per line, (text, kind) spans covering the whole line; works on incomplete code too."""
    lines = text.split("\n")
    kinds = [["text"] * len(line) for line in lines]

    def paint(start: tuple[int, int], end: tuple[int, int], kind: str) -> None:
        for row in range(max(1, start[0]), min(len(lines), end[0]) + 1):
            lo = start[1] if row == start[0] else 0
            hi = min(end[1] if row == end[0] else len(lines[row - 1]), len(lines[row - 1]))
            kinds[row - 1][lo:hi] = [kind] * max(0, hi - lo)

    definition = decorator = False
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            kind = "text"
            if token.type == tokenize.NAME:
                if definition:
                    kind, definition = "definition", False
                elif keyword.iskeyword(token.string) or keyword.issoftkeyword(token.string):
                    kind, definition = "keyword", token.string in ("class", "def")
                elif decorator:
                    kind = "decorator"
                elif token.string in CAD_NAMES:
                    kind = "cad"
                elif token.string in BUILTINS:
                    kind = "builtin"
            elif token.type == tokenize.STRING or tokenize.tok_name[token.type].startswith("FSTRING"):
                kind = "string"
            elif token.type == tokenize.NUMBER:
                kind = "number"
            elif token.type == tokenize.COMMENT:
                kind = "comment"
            elif token.string == "@" and not lines[token.start[0] - 1][:token.start[1]].strip():
                decorator, kind = True, "decorator"
            if token.type in (tokenize.NEWLINE, tokenize.NL) or token.string == "(":
                decorator = False
            paint(token.start, token.end, kind)
    except (tokenize.TokenError, SyntaxError) as exc:
        if isinstance(exc, tokenize.TokenError) and "multi-line string" in exc.args[0]:
            paint(exc.args[1], (len(lines), len(lines[-1])), "string")
    result = []
    for line, styles in zip(lines, kinds):
        spans = []
        start = 0
        while start < len(line):
            end = start + 1
            while end < len(line) and styles[end] == styles[start]:
                end += 1
            spans.append((line[start:end], styles[start]))
            start = end
        result.append(tuple(spans))
    return tuple(result)


def _column(line: str, x: float, char_width: float) -> int:
    """Character index under a horizontal pixel offset (tabs are 4 columns wide)."""
    target = max(0.0, x / char_width)
    visual = 0
    for index, char in enumerate(line):
        following = visual + (4 - visual % 4 if char == "\t" else 1)
        if target < (visual + following) / 2:
            return index
        visual = following
    return len(line)


MOVES = {  # key -> (textedit key, with Ctrl)
    glfw.KEY_LEFT: ("left", "word_left"), glfw.KEY_RIGHT: ("right", "word_right"),
    glfw.KEY_UP: ("up", "up"), glfw.KEY_DOWN: ("down", "down"),
    glfw.KEY_HOME: ("home", "doc_start"), glfw.KEY_END: ("end", "doc_end"),
    glfw.KEY_PAGE_UP: ("page_up", "page_up"), glfw.KEY_PAGE_DOWN: ("page_down", "page_down"),
    glfw.KEY_BACKSPACE: ("backspace", "word_backspace"), glfw.KEY_DELETE: ("delete", "word_delete"),
}


def copy_text(text: str) -> None:
    """Put text on the system clipboard."""
    glfw.set_clipboard_string(None, text)  # pyright: ignore[reportArgumentType]  # GLFW takes None; its stub does not


def _keyboard(editor: Editor, events: list, page_lines: int, focused: bool = True) -> Editor:
    """Apply typed text and editing keys (only when focused) and call the window's actions (see
    ui.shortcuts), all in the order they arrived."""
    for event in events:
        if callable(event):
            event(editor)
        elif focused and isinstance(event, str):
            editor = textedit.insert(editor, event, typing=True)
        if callable(event) or not focused or isinstance(event, str):
            continue
        key, mods, repeat = event
        ctrl, shift = bool(mods & glfw.MOD_CONTROL), bool(mods & glfw.MOD_SHIFT)
        if key in MOVES:
            editor = textedit.key(editor, MOVES[key][ctrl], shift, page_lines)
        elif key == glfw.KEY_TAB:
            editor = textedit.key(editor, "untab" if shift else "tab")
        elif key in (glfw.KEY_ENTER, glfw.KEY_KP_ENTER) and not ctrl:
            editor = textedit.key(editor, "enter")
        elif not ctrl:
            continue
        elif key == glfw.KEY_Z:
            editor = textedit.redo(editor) if shift else textedit.undo(editor)
        elif key == glfw.KEY_Y:
            editor = textedit.redo(editor)
        elif key == glfw.KEY_V:
            editor = textedit.insert(editor, clipboard_text())
        elif repeat:
            continue
        elif key == glfw.KEY_A:
            editor = textedit.key(editor, "select_all")
        elif key == glfw.KEY_C:
            lo, hi = textedit.copy_range(editor)
            copy_text(editor.text[lo:hi])
        elif key == glfw.KEY_X:
            editor, text = textedit.cut(editor)
            copy_text(text)
    return editor


def view(editor: Editor, size: tuple[float, float], events: list, error_line: int | None,
         wheel_scroll: bool = True) -> Editor:
    """Draw the visible lines and handle input (when focused). Returns the (maybe) edited editor.
    wheel_scroll False: the mouse wheel does not scroll (Ctrl+wheel zooms instead)."""
    flags = imgui.WindowFlags.HORIZONTAL_SCROLLBAR
    if not wheel_scroll:
        flags |= imgui.WindowFlags.NO_SCROLL_WITH_MOUSE
    visible = imgui.begin_child("editor", size, imgui.ChildFlags.NONE, flags)
    try:
        if not visible:
            return _keyboard(editor, events, 1, focused=False)
        lines = editor.text.split("\n")
        spans = highlight(editor.text)
        height = imgui.get_text_line_height_with_spacing()
        char_width = imgui.calc_text_size("M" * 64)[0] / 64  # one character is rounded up; zoomed sizes are fractional
        gutter = char_width * (len(str(len(lines))) + 2)
        origin = imgui.get_cursor_screen_pos()
        available = imgui.get_content_region_avail()
        longest = max(len(line.expandtabs(4)) for line in lines)
        content_width = max(gutter + (longest + 2) * char_width, available[0])
        imgui.invisible_button("##source", (content_width, max(len(lines) * height, available[1])))
        hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
        io_state = imgui.get_io()

        # Mouse: click places the cursor, drag selects (scrolling at the borders), 2/3 clicks select word/line.
        clicked = hovered and imgui.is_mouse_clicked(imgui.MouseButton.LEFT)
        dragging = active and imgui.is_mouse_dragging(imgui.MouseButton.LEFT)
        if clicked or dragging:
            imgui.set_window_focus()
            x, y = io_state.mouse_pos
            row = max(0, min(len(lines) - 1, int((y - origin[1]) / height)))
            column = _column(lines[row], x - origin[0] - gutter, char_width)
            clicks = max(1, imgui.get_mouse_clicked_count(imgui.MouseButton.LEFT)) if clicked else 1
            editor = textedit.click(editor, row, column, extend=io_state.key_shift or not clicked, clicks=clicks)
            if dragging:
                (left, top), (width, window_height) = imgui.get_window_pos(), imgui.get_window_size()
                if not top <= y <= top + window_height:
                    imgui.set_scroll_y(max(0.0, imgui.get_scroll_y() + (y - top if y < top else y - top - window_height)))
                if not left <= x <= left + width:
                    imgui.set_scroll_x(max(0.0, imgui.get_scroll_x() + (x - left if x < left else x - left - width)))
        if hovered:
            imgui.set_mouse_cursor(imgui.MouseCursor.TEXT_INPUT)

        focused = imgui.is_window_focused()
        editor = _keyboard(editor, events, max(1, int(size[1] / height) - 1), focused)
        if editor.text != "\n".join(lines):
            lines = editor.text.split("\n")
            spans = highlight(editor.text)

        row, col = textedit.line_col(editor.text, editor.cursor)
        cursor_x = gutter + len(lines[row][:col].expandtabs(4)) * char_width
        cursor_y = row * height
        if editor.reveal:  # scroll the cursor into view once
            scroll_x, scroll_y = imgui.get_scroll_x(), imgui.get_scroll_y()
            window_w, window_h = imgui.get_window_size()
            if cursor_y < scroll_y or cursor_y + 2 * height > scroll_y + window_h:
                imgui.set_scroll_y(max(0.0, cursor_y - window_h / 2))
            if cursor_x < scroll_x or cursor_x + 3 * char_width > scroll_x + window_w:
                imgui.set_scroll_x(max(0.0, cursor_x - window_w / 2))
            editor = replace(editor, reveal=False)

        draw = imgui.get_window_draw_list()
        color = imgui.get_color_u32
        lo, hi = textedit.selection(editor)
        first = max(0, int(imgui.get_scroll_y() / height) - 1)
        position = sum(len(line) + 1 for line in lines[:first])
        for index in range(first, min(len(lines), first + int(size[1] / height) + 3)):
            line, y = lines[index], origin[1] + index * height
            right = origin[0] + content_width
            if index == row:
                draw.add_rect_filled((origin[0], y), (right, y + height), color(CURRENT_LINE))
            if index + 1 == error_line:
                draw.add_rect_filled((origin[0], y), (right, y + height), color(ERROR_LINE))
            if lo < hi and hi > position and lo <= position + len(line):
                a = len(line[:max(0, lo - position)].expandtabs(4))
                b = len(line[:max(0, hi - position)].expandtabs(4)) + (hi > position + len(line))
                draw.add_rect_filled((origin[0] + gutter + a * char_width, y),
                                     (origin[0] + gutter + b * char_width, y + height), color(SELECTION))
            number = str(index + 1)
            draw.add_text((origin[0] + gutter - (len(number) + 1) * char_width, y), color(COLORS["comment"]), number)
            prefix = ""
            for text, kind in spans[index]:
                before = len(prefix.expandtabs(4))
                prefix += text
                draw.add_text((origin[0] + gutter + before * char_width, y), color(COLORS[kind]),
                              prefix.expandtabs(4)[before:])
            position += len(line) + 1
        if focused and imgui.get_time() % 1.1 < 0.7:  # blinking cursor
            x, y = origin[0] + cursor_x, origin[1] + cursor_y
            draw.add_line((x, y), (x, y + height - 2.0), color(COLORS["text"]), 1.0)
        return editor
    finally:
        imgui.end_child()
