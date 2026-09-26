from dataclasses import replace

import pytest

from pycodecad import textedit as te


def test_typing_groups_into_one_undo_step():
    editor = te.load("")
    for char in "abc":
        editor = te.insert(editor, char, typing=True)
    editor = te.key(editor, "enter")
    editor = te.insert(editor, "d", typing=True)
    assert editor.text == "abc\nd"
    assert te.undo(editor).text == "abc\n"
    assert te.undo(te.undo(editor)).text == "abc"
    assert te.undo(te.undo(te.undo(editor))).text == ""
    assert te.redo(te.undo(editor)).text == "abc\nd"


def test_enter_keeps_indentation_and_indents_after_colon():
    editor = te.key(te.load("    if x:"), "doc_end")
    assert te.key(editor, "enter").text == "    if x:\n        "


def test_tab_untab_and_backspace_to_tab_stop():
    editor = te.key(te.load("a\nb"), "select_all")
    editor = te.key(editor, "tab")
    assert editor.text == "    a\n    b"
    assert te.key(editor, "untab").text == "a\nb"
    editor = te.key(te.load("      x"), "doc_start")
    editor = te.click(editor, 0, 6)
    assert te.key(editor, "backspace").text == "    x"


def test_movement_selection_and_words():
    editor = te.load("hello world\nsecond")
    assert te.key(editor, "word_right").cursor == 6
    editor = te.key(te.key(editor, "end", shift=True), "down")
    assert editor.cursor == len("hello world\nsecond")
    editor = te.click(te.load("hello world"), 0, 7, clicks=2)
    assert te.selection(editor) == (6, 11)
    assert te.key(te.load("abc def"), "doc_end").cursor == 7


def test_cut_without_selection_takes_the_line():
    editor, text = te.cut(te.load("one\ntwo\n"))
    assert (text, editor.text) == ("one\n", "two\n")
    assert te.undo(editor).text == "one\ntwo\n"


def test_replace_all_is_undoable_and_keeps_cursor():
    editor = te.click(te.load("abcdef"), 0, 4)
    editor = te.replace_all(editor, "xy")
    assert (editor.text, editor.cursor) == ("xy", 2)
    assert te.undo(editor).text == "abcdef"


def test_invalid_editors_cannot_be_built():
    editor = te.key(te.load("abc"), "doc_end")
    for bad in (dict(cursor=4), dict(anchor=4), dict(cursor=-1), dict(anchor=-1),
                dict(undo=(("ab", 0),)), dict(redo=[te.Snapshot(text="", cursor=0)]),
                dict(text="ab"), dict(anchor=0, text=""), dict(reveal=1)):
        with pytest.raises((ValueError, TypeError)):
            replace(editor, **bad)
    with pytest.raises(TypeError):
        te.Editor("abc")  # pyright: ignore[reportCallIssue]  # keyword only
    for text, cursor in (("ab", 3), ("", 1), ("ab", -1)):
        with pytest.raises(ValueError):
            te.Snapshot(text=text, cursor=cursor)
    history = (te.Snapshot(text="", cursor=0), te.Snapshot(text="ab", cursor=2))
    assert replace(editor, cursor=3, anchor=0, undo=history).cursor == 3


def test_undo_restores_a_cursor_within_its_text():
    editor = te.key(te.load("hello"), "doc_end")
    editor = te.replace_all(editor, "hi")
    assert (editor.text, editor.cursor) == ("hi", 2)
    editor = te.undo(editor)
    assert (editor.text, editor.cursor) == ("hello", 5)
    assert te.redo(editor).cursor == 2


def test_history_stays_at_its_limit():
    editor = te.load("")
    for _ in range(te.HISTORY + 10):
        editor = te.insert(editor, "x")
    assert len(editor.undo) == te.HISTORY
