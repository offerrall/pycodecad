"""What a Workspace looks like: a top bar, the folder's files on the left, then the code (with the
parameters of exposed functions above it), the 3D view (a Viewer) on the right and a status line. Drawn every frame with
Dear ImGui into the current region; buttons call Workspace and Viewer methods directly.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import glfw
from slimgui import imgui

from .api import FPS
from . import camera as cam
from . import editor, textedit, viewcube
from .icons import icon
from .imgui_backend import FONT_SIZE, clipboard_text

if TYPE_CHECKING:
    from .params import Param
    from .viewer import Viewer
    from .window import Window
    from .workspace import Workspace

STATUS_HEIGHT = 22.0
TOOL_SIDE = 28.0  # the square top-bar buttons
VIEW_SIDE = 26.0  # the 3D view's buttons
SMALL_SIDE = 22.0  # Copy error, Reset, Play/Pause
ICON_SIZE = 16.0
GROUP_GAP = 7.0
CUBE_RADIUS = 32.0  # half the view cube's side, in pixels
CUBE_MARGIN = 68.0  # from the view's top right corner to the cube's centre
EXPORTS = (("STL (3D printing)", "stl", "generic"), ("3MF", "3mf", "generic"),
           ("3MF for Bambu Studio", "3mf", "bambu"), ("STEP (CAD)", "step", "generic"),
           ("GLB (web)", "glb", "generic"), ("BREP (OpenCascade)", "brep", "generic"))
ERROR = (1.0, 0.42, 0.38, 1.0)
WARNING = (0.96, 0.69, 0.16, 1.0)
MUTED = (0.62, 0.64, 0.70, 1.0)
OVERLAY = (0.10, 0.11, 0.14, 0.72)
BACKGROUND = (0.075, 0.08, 0.095, 1.0)
CUBE_FACE = (0.36, 0.40, 0.49, 0.94)
CUBE_EDGE = (0.60, 0.64, 0.73, 1.0)
CUBE_TEXT = (0.88, 0.90, 0.94, 1.0)
CUBE_HOVER = (0.96, 0.69, 0.16, 0.9)  # brand gold
# Button colours (normal, hovered, active, icon): Run in the brand gold, Stop in red.
RUN_COLORS = ((0.96, 0.69, 0.16, 1.0), (1.0, 0.78, 0.32, 1.0), (0.85, 0.60, 0.12, 1.0), (0.10, 0.07, 0.0, 1.0))
STOP_COLORS = ((0.78, 0.30, 0.27, 1.0), (0.88, 0.38, 0.34, 1.0), (0.68, 0.25, 0.22, 1.0), (1.0, 1.0, 1.0, 1.0))
STYLE_COLORS = {
    imgui.Col.WINDOW_BG: BACKGROUND,
    imgui.Col.CHILD_BG: (0.095, 0.10, 0.12, 1.0),
    imgui.Col.POPUP_BG: (0.11, 0.12, 0.15, 0.98),
    imgui.Col.BORDER: (0.16, 0.17, 0.21, 1.0),
    imgui.Col.BUTTON: (0.16, 0.17, 0.21, 1.0),
    imgui.Col.BUTTON_HOVERED: (0.24, 0.26, 0.32, 1.0),
    imgui.Col.BUTTON_ACTIVE: (0.30, 0.33, 0.42, 1.0),
    imgui.Col.HEADER_HOVERED: (0.24, 0.26, 0.32, 1.0),
    imgui.Col.FRAME_BG: (0.14, 0.15, 0.18, 1.0),
    imgui.Col.CHECK_MARK: WARNING,  # brand gold
}


def apply_style() -> None:
    imgui.style_colors_dark()
    style = imgui.get_style()
    style.window_rounding = 0.0
    style.frame_rounding = style.child_rounding = style.popup_rounding = 4.0
    style.frame_padding = (8.0, 4.0)
    style.item_spacing = (6.0, 4.0)
    for col, value in STYLE_COLORS.items():
        style.colors[col] = value


def region() -> tuple[float, float]:
    """The available region of the current ImGui window (at least a pixel)."""
    width, height = imgui.get_content_region_avail()
    return max(1.0, width), max(1.0, height)


def workspace(ws: Workspace, events: list) -> None:
    """A Workspace in the current region. events: this frame's keyboard input (see ImguiBackend.events)."""
    imgui.push_style_color(imgui.Col.CHILD_BG, (0.0, 0.0, 0.0, 0.0))  # the host window's background
    imgui.begin_child(f"workspace##{id(ws)}", region())
    imgui.pop_style_color()
    if ws.read_only:
        read_only_band(ws)
    if imgui.is_window_focused(imgui.FocusedFlags.ROOT_AND_CHILD_WINDOWS):  # not while another ImGui window is
        events = shortcuts(ws, events)
    if ws.read_only:  # no editor calls the shortcuts' actions
        for event in events:
            if callable(event):
                event(ws.editor)
    topbar(ws)
    panels(ws, events)
    statusbar(ws)
    if ws.save_as_open:
        save_as_dialog(ws)
    if ws.opening:
        open_prompt(ws)
    imgui.end_child()


def shortcuts(ws: Workspace, events: list) -> list:
    """Ctrl+R, F5 or Ctrl+Enter: Run; Ctrl+S: Save; Ctrl+Shift+S: Save as; Ctrl +/-/0: code zoom. They
    work wherever the focus is, except in a dialog, a menu or a text field. Returns the events with
    these keys replaced by actions, which the editor calls in order: text typed before Ctrl+S is saved."""
    if imgui.is_popup_open("", imgui.PopupFlags.ANY_POPUP) or imgui.get_io().want_text_input:
        return events

    def action(do):
        def act(editor) -> None:
            ws.editor = editor  # the edits that came before the shortcut
            do()
        return act

    result = []
    for event in events:
        key, mods, repeat = event if isinstance(event, tuple) else (None, 0, False)
        ctrl = mods & glfw.MOD_CONTROL
        if key == glfw.KEY_F5 or ctrl and key in (glfw.KEY_R, glfw.KEY_ENTER, glfw.KEY_KP_ENTER):
            if not repeat:
                result.append(action(ws.run))
        elif ctrl and (step := zoom_step(key)) is not None:
            result.append(action(lambda step=step: ws.zoom_code(step)))
        elif ctrl and key == glfw.KEY_S and not ws.read_only:
            if not repeat and mods & glfw.MOD_SHIFT:
                result.append(action(lambda: setattr(ws, "save_as_open", True)))
            elif not repeat:
                result.append(action(ws.save))
        else:
            result.append(event)
    return result


def zoom_step(key: int | None) -> int | None:
    """Ctrl with +, - or 0 zooms the code: by the character the key types, so it works on any
    keyboard layout (on a Spanish one + and - are not where the US names put them), or the keypad."""
    if key is None:
        return None
    keypad = {glfw.KEY_KP_ADD: 1, glfw.KEY_KP_SUBTRACT: -1, glfw.KEY_KP_0: 0}
    if key in keypad:
        return keypad[key]
    with warnings.catch_warnings():  # without a window (tests) GLFW is not initialized: US names
        warnings.simplefilter("ignore", glfw.GLFWError)
        name = glfw.get_key_name(key, 0)
    name = name or {glfw.KEY_EQUAL: "=", glfw.KEY_MINUS: "-", glfw.KEY_0: "0"}.get(key)
    return {"+": 1, "=": 1, "-": -1, "0": 0}.get(name) if name else None


def read_only_band(ws: Workspace) -> None:
    imgui.push_style_color(imgui.Col.CHILD_BG, WARNING)
    imgui.begin_child("read-only", (0.0, imgui.get_frame_height()))
    imgui.set_cursor_pos((8.0, 3.0))
    imgui.text_colored((0.1, 0.07, 0.0, 1.0), "READ ONLY: set the parameters, Run, Export. The scripts are never "
                       "changed.")
    imgui.end_child()
    imgui.pop_style_color()


def unsaved_prompt(ws: Workspace, question: str) -> str | None:
    """A modal asking to Save / Discard / Cancel the editor's unsaved changes: "go" once they are
    saved or discarded, "cancel", or None while there is no answer (a failed save keeps asking)."""
    answer = None
    imgui.push_id(str(id(ws)))
    imgui.open_popup("Unsaved changes")
    if imgui.begin_popup_modal("Unsaved changes", flags=imgui.WindowFlags.ALWAYS_AUTO_RESIZE)[0]:
        imgui.text(question)
        if imgui.button("Save") and ws.save():
            answer = "go"
        imgui.same_line()
        if imgui.button("Discard"):
            ws.discard()
            answer = "go"
        imgui.same_line()
        if imgui.button("Cancel"):
            answer = "cancel"
        if ws.message_is_error:
            imgui.text_colored(ERROR, ws.message)
        if answer:
            imgui.close_current_popup()
        imgui.end_popup()
    imgui.pop_id()
    return answer


def close_prompt(ws: Workspace, window: Window) -> None:
    if not window.close_requested:
        return
    answer = unsaved_prompt(ws, f"Save the changes to {ws.path.name} before closing?")
    if answer:
        window.close_requested = False
    if answer == "go":
        window.request_close()


def open_file(ws: Workspace, path: Path, line: int | None = None) -> None:
    """Edit another file: at once, or after the Save / Discard / Cancel prompt (see open_prompt)."""
    if ws.dirty() and path != ws.path:
        ws.opening = (path, line)
    else:
        ws.open(path, line)


def open_prompt(ws: Workspace) -> None:
    """Another file was asked for while the editor had unsaved changes: Save / Discard / Cancel."""
    assert ws.opening is not None
    path, line = ws.opening
    answer = unsaved_prompt(ws, f"Save the changes to {ws.path.name} before opening {path.name}?")
    if answer:
        ws.opening = None
    if answer == "go":
        ws.open(path, line)


def tooltip(name: str, shortcut: str = "") -> None:
    """The hovered item's name, and its shortcut in grey."""
    if imgui.begin_item_tooltip():
        imgui.text(name)
        if shortcut:
            imgui.same_line(spacing=12.0)
            imgui.text_colored(MUTED, shortcut)
        imgui.end_tooltip()


def button(label: str, name: str, shortcut: str = "") -> bool:
    pressed = imgui.button(label)
    tooltip(name, shortcut)
    return pressed


def icon_button(name: str, tip: str, shortcut: str = "", side: float = TOOL_SIDE, colors: tuple = ()) -> bool:
    """A square button that shows one icon; tip (and shortcut) on hover. colors: (normal, hovered,
    active, icon) to paint it, e.g. the Run button."""
    for col, value in zip((imgui.Col.BUTTON, imgui.Col.BUTTON_HOVERED, imgui.Col.BUTTON_ACTIVE, imgui.Col.TEXT),
                          colors):
        imgui.push_style_color(col, value)
    imgui.push_font(None, ICON_SIZE if side >= VIEW_SIDE else ICON_SIZE - 2.0)
    pressed = imgui.button(f"{icon(name)}##{name}", (side, side))
    imgui.pop_font()
    imgui.pop_style_color(len(colors))
    tooltip(tip, shortcut)
    return pressed


def flat_icon_button(name: str, tip: str) -> bool:
    """A small icon button without a background until hovered (Copy error, Reset)."""
    imgui.push_style_color(imgui.Col.BUTTON, (0.0, 0.0, 0.0, 0.0))
    pressed = icon_button(name, tip, side=SMALL_SIDE)
    imgui.pop_style_color()
    return pressed


def group_gap() -> None:
    """A thin vertical line between groups of top-bar buttons."""
    imgui.same_line(spacing=GROUP_GAP)
    x, y = imgui.get_cursor_screen_pos()
    imgui.get_window_draw_list().add_line((x, y + 6.0), (x, y + TOOL_SIDE - 6.0),
                                          imgui.get_color_u32(STYLE_COLORS[imgui.Col.BORDER]), 1.0)
    imgui.same_line(spacing=GROUP_GAP + 1.0)


def topbar(ws: Workspace) -> None:
    top = imgui.get_cursor_pos_y()
    imgui.push_style_color(imgui.Col.BUTTON, (0.0, 0.0, 0.0, 0.0))  # flat until hovered
    if ws.child is not None and time.monotonic() - ws.run_started > 0.5:
        if icon_button("square", "Stop", colors=STOP_COLORS):
            ws.stop()
    elif icon_button("play", "Run", "Ctrl+R / F5", colors=RUN_COLORS):
        ws.run()
    group_gap()
    if not ws.read_only:  # read only: no code to save, copy or hand to an assistant
        code_buttons(ws)
    if icon_button("download", "Export"):
        imgui.open_popup("export")
    imgui.pop_style_color()
    if imgui.begin_popup("export"):
        for label, extension, profile in EXPORTS:
            if imgui.menu_item(label)[0]:
                ws.export(extension, profile)
        imgui.separator()
        if imgui.menu_item("PNG picture of the view")[0]:
            ws.save_picture()
        imgui.end_popup()
    text_y = top + round((TOOL_SIDE - imgui.get_text_line_height()) / 2) - 4.0  # the font sits low in its line
    if ws.disk_changed and not ws.read_only:
        imgui.same_line(spacing=16.0)
        lost = " (your unsaved edits here would be lost)" if ws.dirty() else ""
        imgui.set_cursor_pos_y(text_y)
        imgui.text_colored(WARNING, f"Changed on disk{lost}:")
        imgui.same_line()
        imgui.set_cursor_pos_y(top + (TOOL_SIDE - imgui.get_frame_height()) / 2)
        if button(f"{icon('refresh-cw')} Reload", "Load the file from disk; then Run to see it"):
            ws.reload()
    if ws.inputs_changed:  # a helper module or asset changed (e.g. by an AI assistant): Run shows it
        imgui.same_line(spacing=16.0)
        imgui.set_cursor_pos_y(text_y)
        more = f" and {len(ws.inputs_changed) - 1} more" if len(ws.inputs_changed) > 1 else ""
        imgui.text_colored(WARNING, f"{Path(ws.inputs_changed[0]).name}{more} changed on disk: Run to see it")
    name = ws.path.name
    runs = f"  ·  Run: {ws.main.name}" if ws.path != ws.main else ""  # the main, when another file is edited
    width = imgui.calc_text_size(name + runs)[0]
    imgui.same_line(max(imgui.get_cursor_pos()[0], imgui.get_window_width() - width - 6.0))
    imgui.set_cursor_pos_y(text_y)
    if ws.dirty():  # a red dot: the editor differs from the file
        x, y = imgui.get_cursor_screen_pos()
        imgui.get_window_draw_list().add_circle_filled((x - 10.0, y + imgui.get_text_line_height() / 2 + 4.0), 4.0,
                                                       imgui.get_color_u32(ERROR))
    imgui.text_colored(MUTED, name + runs)
    imgui.set_cursor_pos_y(top + TOOL_SIDE + imgui.get_style().item_spacing[1])


def code_buttons(ws: Workspace) -> None:
    if icon_button("save", "Save", "Ctrl+S"):
        ws.save()
    imgui.same_line()
    if icon_button("file-plus-2", "Save as (a new file, and continue there)", "Ctrl+Shift+S"):
        ws.save_as_open = True
    group_gap()
    if icon_button("sparkles", "Copy AI context (lets an AI assistant work on the main file)"):
        from .context import ai_context

        editor.copy_text(ai_context(ws.main, ws))
        ws.say("AI context copied: paste it into your assistant")
    imgui.same_line()
    if icon_button("copy", "Copy code"):
        editor.copy_text(ws.editor.text)
        ws.say("Code copied")
    imgui.same_line()
    if icon_button("clipboard-paste", "Paste code (replaces all the code)"):
        ws.editor = textedit.replace_all(ws.editor, clipboard_text())
    group_gap()


def file_list(ws: Workspace, height: float) -> float:
    """The folder's .py files, a narrow column: the edited one selected, the main one marked with
    a play icon (a right click makes another the main; read only: a click runs a file). Returns its
    width (0 when not shown)."""
    if not ws.show_files:
        return 0.0
    files = ws.files()
    names = [path.name for path in files]
    marker = f"{icon('play')} "
    padding = imgui.get_style().window_padding[0] * 2 + imgui.get_style().item_spacing[0]
    width = min(200.0, max(110.0, imgui.calc_text_size(marker)[0] + padding
                           + max(imgui.calc_text_size(name)[0] for name in names)))
    imgui.begin_child("files", (width, height), imgui.ChildFlags.BORDERS)
    indent = imgui.calc_text_size(marker)[0]
    for path, name in zip(files, names):
        main = path == ws.main
        imgui.push_id(str(path))
        if imgui.selectable(f"##{name}", path == ws.path)[0]:
            ws.choose(path) if ws.read_only else open_file(ws, path)
        if ws.read_only:
            tooltip(f"{name}: Run runs it" if main else f"Run {name}")
        else:
            tooltip(f"{name}: the main file, Run runs it" if main else f"{name}: right click to make it the main file")
        if not ws.read_only and imgui.begin_popup_context_item("main"):
            if imgui.menu_item("Main file (Run runs it)", selected=main)[0]:
                ws.set_main(path)
            imgui.end_popup()
        imgui.same_line(imgui.get_style().window_padding[0])
        if main:
            imgui.text_colored(WARNING, icon("play"))  # brand gold, as the Run button
            imgui.same_line(imgui.get_style().window_padding[0] + indent)
        else:
            imgui.set_cursor_pos_x(imgui.get_style().window_padding[0] + indent)
        imgui.text(name)
        imgui.pop_id()
    imgui.end_child()
    imgui.same_line(spacing=6.0)
    return width + 6.0


def panels(ws: Workspace, events: list) -> None:
    width, height = imgui.get_content_region_avail()
    height -= STATUS_HEIGHT
    width -= file_list(ws, height)
    left = max(260.0, min(width - 300.0, width * ws.split))

    imgui.begin_child("left", (left, height))
    error = ws.error
    output = None if error else ws.stdout.strip()
    bottom = min(height * 0.35, 190.0) if error or output else 0.0
    if ws.read_only:  # no code: the parameters fill the column
        controls = height - bottom - (4.0 if bottom else 0.0)
    else:
        controls = parameters_height(ws, height * 0.45)
    code = height - bottom - controls - (4.0 if bottom else 0.0) - (4.0 if controls else 0.0)
    if controls:
        imgui.begin_child("parameters", (0.0, controls), imgui.ChildFlags.BORDERS)
        parameters(ws)
        imgui.end_child()
    if not ws.read_only:
        code_view(ws, code, events)
    in_this_file = ws.error_file == str(ws.path)
    if error:  # the error message first, then where, then its traceback
        imgui.begin_child("error", (0.0, 0.0), imgui.ChildFlags.BORDERS)
        start_x, start_y = imgui.get_cursor_pos()
        copy_x = start_x + imgui.get_content_region_avail()[0] - SMALL_SIDE
        lines = error.strip().splitlines()
        imgui.push_text_wrap_pos(copy_x - 6.0)  # the copy button sits top right
        imgui.text_colored(ERROR, lines[-1])
        if ws.error_file and not in_this_file and not ws.read_only:  # a click opens that file at that line
            where = Path(ws.error_file)
            shown = where.relative_to(ws.folder) if where.is_relative_to(ws.folder) else where
            imgui.text_colored(WARNING, f"in {shown}, line {ws.error_line}")
            if imgui.is_item_hovered():
                imgui.set_mouse_cursor(imgui.MouseCursor.HAND)
            tooltip(f"Open {where.name} at line {ws.error_line}")
            if imgui.is_item_clicked():
                open_file(ws, where, ws.error_line)
        for line in lines[:-1]:
            imgui.text_colored(MUTED, line)
        imgui.pop_text_wrap_pos()
        imgui.set_cursor_pos((copy_x, start_y))
        if flat_icon_button("copy", "Copy error"):
            editor.copy_text(error)
            ws.say("Error copied")
        imgui.end_child()
    elif output:  # what the script printed
        imgui.begin_child("output", (0.0, 0.0), imgui.ChildFlags.BORDERS)
        imgui.text_colored(MUTED, output[-5000:])
        imgui.end_child()
    imgui.end_child()

    imgui.same_line(spacing=0.0)
    imgui.invisible_button("split", (6.0, height))
    if imgui.is_item_hovered() or imgui.is_item_active():
        imgui.set_mouse_cursor(imgui.MouseCursor.RESIZE_EW)
    if imgui.is_item_active():
        ws.split = min(0.8, max(0.15, ws.split + imgui.get_io().mouse_delta[0] / width))
    imgui.same_line(spacing=0.0)
    top_left = imgui.get_cursor_screen_pos()
    bar = imgui.get_frame_height_with_spacing() + 6.0 if ws.frames else 0.0
    view_width = imgui.get_content_region_avail()[0]
    ws.viewer.draw(ws.on_screen(), (view_width, height - bar))
    if ws.frames:
        imgui.set_cursor_screen_pos((top_left[0], top_left[1] + height - bar + 4.0))
        timeline(ws, view_width)
    if not ws.shown and not ws.frames:
        after = imgui.get_cursor_screen_pos()
        if ws.running():
            hint = "Running..."
        elif ws.error:
            hint = "Nothing shown: see the error"
        elif ws.ran():
            hint = "Nothing shown: call show() in the script"
        else:
            hint = "Press Run (Ctrl+R) to run the script"
        imgui.set_cursor_screen_pos((top_left[0] + 14.0, top_left[1] + 16.0 + imgui.get_frame_height()))
        imgui.text_colored(MUTED, hint)
        imgui.set_cursor_screen_pos(after)


def code_view(ws: Workspace, height: float, events: list) -> None:
    """The editor, with the line of the error marked."""
    imgui.begin_child("code", (0.0, height), imgui.ChildFlags.BORDERS)
    highlight = ws.error_line if ws.error_file == str(ws.path) else None
    io = imgui.get_io()
    if io.key_ctrl and io.mouse_wheel and imgui.is_window_hovered(imgui.HoveredFlags.CHILD_WINDOWS):
        ws.zoom_code(1 if io.mouse_wheel > 0 else -1)
    imgui.push_font(None, FONT_SIZE * ws.code_zoom)
    ws.editor = editor.view(ws.editor, imgui.get_content_region_avail(), events, highlight,
                             wheel_scroll=not io.key_ctrl)
    imgui.pop_font()
    imgui.end_child()


def parameters_height(ws: Workspace, limit: float) -> float:
    """Room for the parameters panel (0 when the last run exposed nothing); it scrolls beyond limit."""
    if not ws.parameters:
        return 0.0
    rows = 1 + sum(2 + len(exposed.params) for exposed in ws.parameters)  # title; header, controls, Reset
    padding = imgui.get_style().window_padding[1] * 2
    return min(limit, rows * imgui.get_frame_height_with_spacing() + padding)


def parameters(ws: Workspace) -> None:
    """One group of controls per exposed function. A change stays in memory until Run."""
    imgui.align_text_to_frame_padding()
    imgui.text("Parameters")
    if ws.values_changed():
        imgui.same_line()
        imgui.text_colored(WARNING, "Values changed: Run (Ctrl+R) to apply")
    if not ws.parameters:  # read only shows the panel anyway
        imgui.text_colored(MUTED, "This script has no parameters (see expose())")
    for exposed in ws.parameters:
        imgui.push_id(exposed.function)
        imgui.push_style_color(imgui.Col.HEADER, STYLE_COLORS[imgui.Col.BUTTON])
        is_open = imgui.collapsing_header(exposed.function, flags=imgui.TreeNodeFlags.DEFAULT_OPEN)[0]
        imgui.pop_style_color()
        if is_open:
            labels = [param.label or param.name for param in exposed.params]
            label_width = max((imgui.calc_text_size(label)[0] for label in labels), default=0.0)
            for param, label in zip(exposed.params, labels):
                imgui.set_next_item_width(-label_width - imgui.get_style().item_inner_spacing[0] - 2.0)
                changed, value = control(f"{label}##{param.name}", param, ws.value(exposed.function, param))
                if param.description:
                    imgui.set_item_tooltip(param.description)
                if changed:
                    ws.set_value(exposed.function, param, value)
            prefix = exposed.function + "."
            imgui.begin_disabled(not any(key.startswith(prefix) for key in ws.values))
            if flat_icon_button("rotate-ccw", f"Reset: back to the defaults of {exposed.function} (on the next Run)"):
                ws.reset(exposed.function)
            imgui.end_disabled()
        imgui.pop_id()


def control(label: str, param: Param, value: object) -> tuple[bool, int | float | bool | str]:
    """The ImGui control for one parameter: slider, number input, checkbox or text. value is of
    the parameter's kind (Workspace keeps only values of that kind)."""
    if param.kind == "bool":
        return imgui.checkbox(label, cast(bool, value))
    if param.kind == "str":
        return imgui.input_text(label, cast(str, value))
    if param.slider:
        low, high = param.min, param.max
        assert low is not None and high is not None  # a slider always has Min and Max (see Param)
        if param.kind == "int":
            return imgui.slider_int(label, cast(int, value), int(low), int(high),
                                    flags=imgui.SliderFlags.ALWAYS_CLAMP)
        changed, number = imgui.slider_float(label, cast(float, value), float(low), float(high), "%g",
                                             flags=imgui.SliderFlags.ALWAYS_CLAMP)
        if changed and param.step:  # snap to the step, counted from Min
            number = low + round((number - low) / param.step) * param.step
        return changed, number
    if param.kind == "int":
        step = int(param.step or 1)
        return imgui.input_int(label, cast(int, value), step, step * 10)
    step = float(param.step or 0.0)
    return imgui.input_float(label, cast(float, value), step, step * 10, "%g")


def timeline(ws: Workspace, width: float) -> None:
    """Play/pause and the frame slider of an animation (frame() in the script), under the view."""
    left = imgui.get_cursor_pos_x()
    if icon_button("pause" if ws.playing else "play", "Pause" if ws.playing else "Play", side=SMALL_SIDE):
        ws.playing = not ws.playing
    imgui.same_line()
    total = len(ws.frames)
    label = f"{ws.frame_index() + 1} / {total}  ({ws.clock % (total / FPS):.1f} s)"
    imgui.set_next_item_width(left + width - imgui.get_cursor_pos_x() - imgui.calc_text_size(label)[0] - 16.0)
    changed, index = imgui.slider_int("##frame", ws.frame_index(), 0, total - 1, "")
    if changed:
        ws.seek(index)
    imgui.same_line()
    imgui.text_colored(MUTED, label)


def view(viewer: Viewer, size: tuple[float, float]) -> None:
    """The 3D view: left drag orbits, right/middle (or shift+left) drag pans, wheel zooms,
    double-click fits."""
    io = imgui.get_io()
    width, height = size
    scale_x, scale_y = io.display_framebuffer_scale
    imgui.push_id(str(id(viewer)))
    texture = viewer.texture(max(1, int(width * scale_x)), max(1, int(height * scale_y)))
    top_left = imgui.get_cursor_screen_pos()
    imgui.image(texture, (width, height), uv0=(0.0, 1.0), uv1=(1.0, 0.0))  # GL images are bottom-up
    imgui.set_cursor_screen_pos(top_left)
    imgui.set_next_item_allow_overlap()  # the view buttons drawn on top still get their clicks
    imgui.invisible_button("view3d", (width, height), imgui.ButtonFlags.MOUSE_BUTTON_LEFT
                           | imgui.ButtonFlags.MOUSE_BUTTON_RIGHT | imgui.ButtonFlags.MOUSE_BUTTON_MIDDLE)
    dx, dy = io.mouse_delta
    if imgui.is_item_active() and (dx or dy):
        if io.mouse_down[0] and not io.key_shift:
            viewer.camera = cam.orbit(viewer.camera, dx, dy)
        else:
            viewer.camera = cam.pan(viewer.camera, dx, dy, min(width, height))
    if imgui.is_item_hovered():
        if io.mouse_wheel:
            viewer.camera = cam.zoom(viewer.camera, io.mouse_wheel)
        if imgui.is_mouse_double_clicked(imgui.MouseButton.LEFT):
            viewer.fit()

    # The view cube top right, Fit and the display toggles under it.
    center = (top_left[0] + width - CUBE_MARGIN, top_left[1] + CUBE_MARGIN)
    view_cube(viewer, center)
    spacing = imgui.get_style().item_spacing[0]
    imgui.set_cursor_screen_pos((center[0] - VIEW_SIDE - spacing / 2, center[1] + CUBE_MARGIN - 8.0))
    imgui.push_style_color(imgui.Col.BUTTON, OVERLAY)
    if icon_button("scan", "Fit", "double-click the view", side=VIEW_SIDE):
        viewer.fit()
    imgui.same_line()
    if icon_button("settings-2", "Edges, grid and axes", side=VIEW_SIDE):
        imgui.open_popup("display")
    imgui.pop_style_color()
    if imgui.begin_popup("display"):
        for label in ("Edges", "Grid", "Axes"):
            changed, value = imgui.checkbox(label, getattr(viewer.display, label.lower()))
            if changed:
                viewer.display = replace(viewer.display, **{label.lower(): value})
        imgui.end_popup()

    imgui.set_cursor_screen_pos(top_left)
    imgui.dummy((width, height))  # the cursor goes on after the view, as after an image
    imgui.pop_id()


def view_cube(viewer: Viewer, center: tuple[float, float]) -> None:
    """The navigation cube: it turns with the camera; a click on a face, edge or corner looks from there."""
    visible = viewcube.faces(viewer.camera, center, CUBE_RADIUS)
    reach = CUBE_RADIUS * 1.75  # the cube's largest extent on screen (half the diagonal is sqrt(3))
    imgui.set_cursor_screen_pos((center[0] - reach, center[1] - reach))
    clicked = imgui.invisible_button("view cube", (2 * reach, 2 * reach))
    hovered = viewcube.hit(visible, imgui.get_mouse_pos()) if imgui.is_item_hovered() else None
    if hovered:
        imgui.set_mouse_cursor(imgui.MouseCursor.HAND)
        tooltip(viewcube.name(hovered))
        if clicked:
            viewer.look_from(hovered)
    draw = imgui.get_window_draw_list()
    color = imgui.get_color_u32
    red, green, blue, opacity = CUBE_FACE
    for face in visible:
        shade = 0.4 + 0.6 * face.light
        draw.add_quad_filled(*face.quad, color((red * shade, green * shade, blue * shade, opacity)))
        for direction, quad in face.cells:
            if direction == hovered:  # an edge or corner lights up on every face it touches
                draw.add_quad_filled(*quad, color(CUBE_HOVER))
    for face in visible:
        draw.add_quad(*face.quad, color(CUBE_EDGE), 1.0)
        size = imgui.calc_text_size(face.label)
        xs = [x for x, _ in face.quad]
        # A label shows only where it fits: it fades out as its face turns away.
        room = max(xs) - min(xs) - size[0] - 2.0
        alpha = min(1.0, max(0.0, room / 6.0)) if face.facing > 0.3 else 0.0
        if alpha:
            dark = hovered == face.normal
            ink = (0.10, 0.07, 0.0, alpha) if dark else CUBE_TEXT[:3] + (alpha,)
            draw.add_text((round(face.center[0] - size[0] / 2), round(face.center[1] - size[1] / 2)), color(ink),
                          face.label)


def statusbar(ws: Workspace) -> None:
    running = ws.child is not None
    if running:
        status = "Running..."
    elif ws.error:
        status = "Error: " + ws.error.strip().splitlines()[-1]
    else:
        took = f" in {ws.duration:.2f} s" if ws.duration is not None else ""
        count = len(ws.shown)
        status = f"{count} object{'' if count == 1 else 's'}{took}"
    imgui.text_colored(ERROR if ws.error and not running else MUTED, status)
    if ws.message:
        imgui.same_line()
        imgui.text_colored(ERROR if ws.message_is_error else MUTED, f" ·  {ws.message}")
    if ws.code_zoom != 1.0:  # the code zoom, right-aligned; a click goes back to 100%
        label = f"{round(ws.code_zoom * 100)}%"
        imgui.same_line(imgui.get_window_width() - imgui.calc_text_size(label)[0] - 6.0)
        imgui.text_colored(MUTED, label)
        if imgui.is_item_clicked():
            ws.zoom_code(0)
        tooltip("Code zoom (click or Ctrl+0: 100%)", "Ctrl+ / Ctrl-")


def save_as_dialog(ws: Workspace) -> None:
    """Ask for a new file name (relative to the current file's folder)."""
    if not imgui.is_popup_open("Save as"):
        imgui.open_popup("Save as")
        ws.save_as_name = f"{ws.path.stem}_copy.py"
        ws.say("")
    if imgui.begin_popup_modal("Save as", flags=imgui.WindowFlags.ALWAYS_AUTO_RESIZE)[0]:
        imgui.text("New file (next to the current one, or a full path):")
        imgui.set_next_item_width(420.0)
        if imgui.is_window_appearing():
            imgui.set_keyboard_focus_here()
        _, ws.save_as_name = imgui.input_text("##name", ws.save_as_name)
        if imgui.button("Save") and ws.save_as(ws.save_as_name):
            ws.save_as_open = False
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel"):
            ws.save_as_open = False
            imgui.close_current_popup()
        if ws.message_is_error:
            imgui.text_colored(ERROR, ws.message)
        imgui.end_popup()
