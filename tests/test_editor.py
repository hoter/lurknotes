"""Markdown editing shortcuts: wrapping, list continuation, marker delete.

Spec §7.3 / plan M3: the document stays plain Markdown text. These tests pin
the exact buffer/caret result so the GTK wiring only has to apply a
:class:`~lurkn.editor.TextEdit`.
"""

from __future__ import annotations

from lurkn.editor import (
    BOLD,
    ITALIC,
    TextEdit,
    continue_list,
    marker_at,
    remove_marker_before_cursor,
    wrap_selection,
)


# -- Ctrl+B / Ctrl+I -----------------------------------------------------


def test_bold_without_a_selection_inserts_the_pair_and_puts_the_caret_inside():
    assert wrap_selection("", 0, 0, BOLD) == TextEdit("****", 2, 2)
    assert wrap_selection("hello", 5, 5, BOLD) == TextEdit("hello****", 7, 7)


def test_italic_without_a_selection_inserts_the_pair_and_puts_the_caret_inside():
    assert wrap_selection("", 0, 0, ITALIC) == TextEdit("**", 1, 1)


def test_bold_wraps_the_selection_and_keeps_it_selected():
    result = wrap_selection("hello world", 6, 11, BOLD)

    assert result.text == "hello **world**"
    assert result.text[result.start : result.end] == "world"


def test_italic_wraps_the_selection_with_single_stars():
    result = wrap_selection("hello world", 0, 5, ITALIC)

    assert result.text == "*hello* world"
    assert result.text[result.start : result.end] == "hello"


def test_wrapping_a_reversed_selection_normalises_the_bounds():
    result = wrap_selection("hello world", 11, 6, BOLD)

    assert result.text == "hello **world**"


def test_wrapping_out_of_range_offsets_clamps_to_the_text():
    result = wrap_selection("abc", -10, 99, BOLD)

    assert result.text == "**abc**"
    assert result.text[result.start : result.end] == "abc"


# -- list recognition ----------------------------------------------------


def test_bullet_numbered_and_task_markers_are_recognised():
    assert marker_at("- foo", 2).kind == "bullet"
    ordered = marker_at("12. foo", 4)
    assert ordered.kind == "ordered"
    assert ordered.number == 12
    assert ordered.number_width == 2
    assert marker_at("[ ] foo", 4).kind == "task"


def test_markers_are_recognised_after_indentation():
    marker = marker_at("  - foo", 4)

    assert marker.kind == "bullet"
    assert marker.indent == "  "
    assert marker.marker_start == 2
    assert marker.content_start == 4


def test_plain_text_has_no_list_marker():
    assert marker_at("just text", 4) is None
    assert marker_at("http://example.com", 4) is None
    assert marker_at("1.foo", 2) is None  # no space after the dot
    assert marker_at("-foo", 1) is None  # no space after the bullet


# -- Enter continues the list -------------------------------------------


def test_enter_continues_a_bullet():
    assert continue_list("- item", 6) == TextEdit("- item\n- ", 9, 9)


def test_enter_continues_an_ordered_item_and_increments_the_number():
    assert continue_list("1. first", 8) == TextEdit("1. first\n2. ", 12, 12)
    assert continue_list("9. ninth", 8) == TextEdit("9. ninth\n10. ", 13, 13)


def test_enter_keeps_the_number_width():
    assert continue_list("08. item", 8) == TextEdit("08. item\n09. ", 13, 13)


def test_enter_continues_a_task():
    assert continue_list("[ ] todo", 8) == TextEdit("[ ] todo\n[ ] ", 13, 13)


def test_enter_continues_a_list_after_indentation():
    assert continue_list("  - item", 8) == TextEdit("  - item\n  - ", 13, 13)


def test_enter_splits_the_item_at_the_caret():
    result = continue_list("- first second", 7)

    assert result == TextEdit("- first\n-  second", 10, 10)


def test_enter_on_an_empty_bullet_exits_the_list():
    assert continue_list("- ", 2) == TextEdit("", 0, 0)


def test_enter_on_an_empty_task_exits_the_list():
    assert continue_list("[ ] ", 4) == TextEdit("", 0, 0)


def test_enter_on_an_empty_ordered_item_exits_the_list():
    assert continue_list("3. ", 3) == TextEdit("", 0, 0)


def test_exiting_an_empty_item_preserves_indentation_and_following_lines():
    result = continue_list("  - \nnext", 4)

    assert result == TextEdit("  \nnext", 2, 2)


def test_enter_outside_a_list_is_not_consumed():
    assert continue_list("plain text", 10) is None
    # The caret is inside the marker itself; let the TextView handle Enter.
    assert continue_list("- item", 1) is None


# -- Backspace after the marker -----------------------------------------


def test_backspace_after_a_bullet_removes_the_marker():
    assert remove_marker_before_cursor("- foo", 2) == TextEdit("foo", 0, 0)


def test_backspace_after_an_ordered_marker_removes_the_whole_marker():
    assert remove_marker_before_cursor("12. foo", 4) == TextEdit("foo", 0, 0)


def test_backspace_after_a_task_marker_removes_the_whole_marker():
    assert remove_marker_before_cursor("[ ] foo", 4) == TextEdit("foo", 0, 0)


def test_backspace_preserves_indentation_when_removing_a_marker():
    assert remove_marker_before_cursor("  - foo", 4) == TextEdit("  foo", 2, 2)


def test_backspace_after_an_empty_marker_leaves_an_empty_line():
    assert remove_marker_before_cursor("- ", 2) == TextEdit("", 0, 0)


def test_backspace_elsewhere_is_not_consumed():
    assert remove_marker_before_cursor("- foo", 3) is None
    assert remove_marker_before_cursor("- foo", 1) is None
    assert remove_marker_before_cursor("plain text", 5) is None
