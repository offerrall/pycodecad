"""Pure text editing: every function takes an Editor and returns a new one.

Positions are character offsets into the text; lines and columns are zero based.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from pytypehint import Min, immutable

HISTORY = 200  # undo steps kept

Position = Annotated[int, Min(0)]


@immutable
class Snapshot:
    """A point in the undo history: a text and a cursor within it."""

    text: str
    cursor: Position

    def __post_init__(self) -> None:
        if self.cursor > len(self.text):
            raise ValueError(f"snapshot cursor {self.cursor} past the end of its text ({len(self.text)})")


@immutable
class Editor:
    """Text, selection (from `anchor` to `cursor`) and undo/redo history of snapshots.
    `reveal` asks the view to scroll the cursor into sight once.
    Every position lies within its text, so an editor can never point past the end."""

    text: str = ""
    cursor: Position = 0
    anchor: Position = 0
    undo: tuple[Snapshot, ...] = ()
    redo: tuple[Snapshot, ...] = ()
    reveal: bool = False

    def __post_init__(self) -> None:
        if self.cursor > len(self.text) or self.anchor > len(self.text):
            raise ValueError(f"cursor {self.cursor} / anchor {self.anchor} past the end of the text ({len(self.text)})")


def line_col(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(offset, len(text)))
    return text.count("\n", 0, offset), offset - text.rfind("\n", 0, offset) - 1


def offset(text: str, line: int, col: int) -> int:
    lines = text.split("\n")
    row = max(0, min(line, len(lines) - 1))
    return sum(len(value) + 1 for value in lines[:row]) + max(0, min(col, len(lines[row])))


def load(text: str) -> Editor:
    """A new document: cursor at the start, no history."""
    return Editor(text=text, reveal=True)


def selection(editor: Editor) -> tuple[int, int]:
    return min(editor.cursor, editor.anchor), max(editor.cursor, editor.anchor)


# --- changing the text ---------------------------------------------------------------------

def _snapshot(editor: Editor) -> Snapshot:
    return Snapshot(text=editor.text, cursor=editor.cursor)


def _checkpoint(editor: Editor) -> Editor:
    """End a typing group: the next change gets its own undo step."""
    if editor.undo and editor.undo[-1].text != editor.text:
        return replace(editor, undo=(editor.undo + (_snapshot(editor),))[-HISTORY:])
    return editor


def change(editor: Editor, text: str, cursor: int, anchor: int | None = None, typing: bool = False) -> Editor:
    """Replace the text, recording undo. Consecutive typed characters share one undo step."""
    anchor = cursor if anchor is None else anchor
    if text == editor.text:
        return replace(editor, cursor=cursor, anchor=anchor, reveal=True)
    history = editor.undo
    grouped = False
    if typing and history and not editor.redo and editor.cursor == editor.anchor:
        before, before_cursor = history[-1].text, history[-1].cursor
        grouped = (editor.cursor > before_cursor and editor.text[:before_cursor] == before[:before_cursor]
                   and editor.text[editor.cursor:] == before[before_cursor:]
                   and "\n" not in editor.text[before_cursor:editor.cursor])
    if not grouped and (not history or history[-1] != _snapshot(editor)):
        history += (_snapshot(editor),)
    result = replace(editor, text=text, cursor=cursor, anchor=anchor, undo=history[-HISTORY:], redo=(), reveal=True)
    return result if typing else _checkpoint(result)


def replace_all(editor: Editor, text: str) -> Editor:
    """Swap the whole text (reload from disk, paste code) as one undoable step, keeping the cursor."""
    return change(editor, text, min(editor.cursor, len(text)), min(editor.anchor, len(text)))


def insert(editor: Editor, text: str, typing: bool = False) -> Editor:
    """Insert over the selection. typing=True groups characters into one undo step."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return editor
    lo, hi = selection(editor)
    return change(editor, editor.text[:lo] + text + editor.text[hi:], lo + len(text),
                  typing=typing and "\n" not in text)


def cut(editor: Editor) -> tuple[Editor, str]:
    """Remove the selection (or the current line) and return it."""
    lo, hi = copy_range(editor)
    return change(_checkpoint(editor), editor.text[:lo] + editor.text[hi:], lo), editor.text[lo:hi]


def copy_range(editor: Editor) -> tuple[int, int]:
    """The selection, or the whole current line when nothing is selected."""
    lo, hi = selection(editor)
    if lo == hi:
        lo = editor.text.rfind("\n", 0, lo) + 1
        end = editor.text.find("\n", hi)
        hi = len(editor.text) if end < 0 else end + 1
    return lo, hi


def undo(editor: Editor) -> Editor:
    return _history(editor, forward=False)


def redo(editor: Editor) -> Editor:
    return _history(editor, forward=True)


def _history(editor: Editor, forward: bool) -> Editor:
    source = editor.redo if forward else editor.undo
    while source and source[-1].text == editor.text:
        source = source[:-1]
    if not source:
        return editor
    text, cursor = source[-1].text, source[-1].cursor
    other = ((editor.undo if forward else editor.redo) + (_snapshot(editor),))[-HISTORY:]
    stacks = dict(redo=source[:-1], undo=other) if forward else dict(undo=source[:-1], redo=other)
    restored = replace(editor, text=text, cursor=cursor, anchor=cursor, reveal=True, **stacks)
    return _checkpoint(restored) if forward else restored


def _indent(editor: Editor, remove: bool) -> Editor:
    """Tab: indent the selected lines (or insert spaces). Shift+Tab: unindent them."""
    lo, hi = selection(editor)
    start = editor.text.rfind("\n", 0, lo) + 1
    if lo == hi and not remove:
        return insert(editor, " " * (4 - len(editor.text[start:lo].expandtabs(4)) % 4))
    lines = editor.text[start:max(lo, hi)].split("\n")
    count = len(lines) - (hi > lo and editor.text[hi - 1:hi] == "\n")
    edits = []  # (position, deleted characters, added text)
    position = start
    for _ in range(count):
        stop = editor.text.find("\n", position)
        line = editor.text[position:stop if stop >= 0 else len(editor.text)]
        if remove:
            deleted = 1 if line.startswith("\t") else min(4, len(line) - len(line.lstrip(" ")))
            edits.append((position, deleted, ""))
        else:
            edits.append((position, 0, "    "))
        position += len(line) + 1
    text = editor.text
    for position, deleted, added in reversed(edits):
        text = text[:position] + added + text[position + deleted:]

    def moved(point: int) -> int:
        return point + sum(len(added) - min(deleted, max(0, point - position))
                           for position, deleted, added in edits if position <= point)

    return change(editor, text, moved(editor.cursor), moved(editor.anchor))


def _char_class(char: str) -> int:
    """0 space, 1 word character, 2 anything else: words and punctuation runs are units."""
    return 0 if char.isspace() else 1 if char.isalnum() or char == "_" else 2


def _word(text: str, position: int, direction: int) -> int:
    """Next word boundary to the left (-1) or right (+1)."""
    if direction < 0:
        while position > 0 and text[position - 1].isspace():
            position -= 1
        if position:
            kind = _char_class(text[position - 1])
            while position > 0 and _char_class(text[position - 1]) == kind:
                position -= 1
        return position
    if position < len(text) and not text[position].isspace():
        kind = _char_class(text[position])
        while position < len(text) and _char_class(text[position]) == kind:
            position += 1
    while position < len(text) and text[position].isspace():
        position += 1
    return position


# --- keys and mouse ------------------------------------------------------------------------

def key(editor: Editor, name: str, shift: bool = False, page_lines: int = 20) -> Editor:
    """An editing or movement key. `shift` extends the selection when moving."""
    text = editor.text
    lo, hi = selection(editor)
    row, col = line_col(text, editor.cursor)
    start = editor.cursor - col
    end = text.find("\n", editor.cursor)
    end = len(text) if end < 0 else end
    editor = _checkpoint(editor)
    if name == "select_all":
        return replace(editor, anchor=0, cursor=len(text), reveal=True)
    if name in ("tab", "untab"):
        return _indent(editor, remove=name == "untab")
    if name == "enter":
        before = text[text.rfind("\n", 0, lo) + 1:lo]
        indentation = before[:len(before) - len(before.lstrip(" \t"))]
        return insert(editor, "\n" + indentation + ("    " if before.rstrip().endswith(":") else ""))
    if name in ("backspace", "delete", "word_backspace", "word_delete"):
        if lo == hi:
            if name == "word_backspace":
                lo = _word(text, lo, -1)
            elif name == "word_delete":
                hi = _word(text, hi, 1)
            elif name == "delete":
                hi = min(len(text), hi + 1)
            elif text[start:lo] and not text[start:lo].strip(" \t"):
                lo = _unindent_point(text, start, lo)  # backspace in indentation: back to the tab stop
            else:
                lo = max(0, lo - 1)
        return change(editor, text[:lo] + text[hi:], lo)
    point = editor.cursor
    if name in ("left", "right"):
        if lo != hi and not shift:
            point = lo if name == "left" else hi
        else:
            point += -1 if name == "left" else 1
    elif name in ("word_left", "word_right"):
        point = _word(text, point, -1 if name == "word_left" else 1)
    elif name in ("up", "down", "page_up", "page_down"):
        lines = page_lines if name.startswith("page") else 1
        point = offset(text, row + (-lines if name in ("up", "page_up") else lines), col)
    elif name == "home":
        first = start + len(text[start:end]) - len(text[start:end].lstrip(" \t"))
        point = start if point == first else first
    elif name == "end":
        point = end
    elif name == "doc_start":
        point = 0
    elif name == "doc_end":
        point = len(text)
    else:
        raise ValueError(f"Unknown editor key: {name}")
    point = max(0, min(point, len(text)))
    return replace(editor, cursor=point, anchor=editor.anchor if shift else point, reveal=True)


def _unindent_point(text: str, start: int, point: int) -> int:
    target = (len(text[start:point].expandtabs(4)) - 1) // 4 * 4
    column = 0
    for index, char in enumerate(text[start:point]):
        column += 4 - column % 4 if char == "\t" else 1
        if column > target:
            return start + index
    return start


def click(editor: Editor, line: int, column: int, extend: bool = False, clicks: int = 1) -> Editor:
    """Mouse press or drag. extend keeps the anchor; 2 clicks select a word, 3 a line."""
    editor = _checkpoint(editor)
    text = editor.text
    point = offset(text, line, column)
    anchor = editor.anchor if extend else point
    if clicks >= 3:
        anchor = text.rfind("\n", 0, point) + 1
        end = text.find("\n", point)
        point = len(text) if end < 0 else end + 1
    elif clicks == 2 and text:
        probe = min(point, len(text) - 1)
        kind = _char_class(text[probe])
        anchor, point = probe, probe + 1
        while anchor > 0 and text[anchor - 1] != "\n" and _char_class(text[anchor - 1]) == kind:
            anchor -= 1
        while point < len(text) and text[point] != "\n" and _char_class(text[point]) == kind:
            point += 1
    return replace(editor, cursor=point, anchor=anchor, reveal=False)
