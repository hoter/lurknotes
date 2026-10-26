"""The fan: tabs for every note, in array order (spec §6.2).

Each tab is a plain ``Gtk.Button`` with a title label, a per-tab motion
controller for the peek, and one ``Gtk.GestureDrag`` for click-or-reorder
(spec §7.2). The gesture is alone on purpose: ``GtkGestureClick`` still emits
``released`` after a drag, so using both would fire two actions (PLATFORM §8).
A release shorter than 5 logical px on both axes is a click; anything longer
is a drag. A drag never moves widgets mid-gesture: the tab is raised with CSS
and the deck is only reordered when the button is released.

The read-only peek is a fixed pane at the bottom of the fan: it is always
allocated, so showing or hiding peek text never changes tab heights, tab
positions, the header, or the wheel target. Tabs stay top-aligned.
"""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gdk, GLib, Graphene, Gtk, Pango

from .. import strings
from ..notes import PREVIEW_LINES, Note
from ..reorder import CLICK, REORDER, DragSession, target_index

# Six 0.9em body lines plus padding; fixed so the pane never resizes.
PEEK_PANE_HEIGHT = 132


class FanPage(Gtk.Box):
    """Read-only list of note tabs. Clicking a tab opens its note."""

    def __init__(
        self,
        on_open: Callable[[str], None],
        on_new: Callable[[], None],
        on_collapse: Callable[[], None],
        on_hover_tab: Callable[[str], None],
        on_leave_tab: Callable[[str], None],
        on_reorder: Callable[[str, int], None],
        on_scrolled: Callable[[], None] | None = None,
        on_drag_begin: Callable[[str], None] | None = None,
        on_drag_update: Callable[[], None] | None = None,
        on_drag_end: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_open = on_open
        self._on_collapse = on_collapse
        self._on_hover_tab = on_hover_tab
        self._on_leave_tab = on_leave_tab
        self._on_reorder = on_reorder
        self._on_scrolled = on_scrolled
        self._on_drag_begin = on_drag_begin
        self._on_drag_update = on_drag_update
        self._on_drag_end = on_drag_end
        self._tabs: dict[str, Gtk.Button] = {}
        self._tab_order: list[str] = []
        self._peek_note: str | None = None
        self._peek_lines: list[str] = []
        # One press on one tab. It stays a click candidate until 5 logical px.
        self._drag: DragSession | None = None
        self._drag_button: Gtk.Button | None = None
        self._drag_start: tuple[float, float] | None = None
        self._drag_target: int | None = None
        self._pending_notes: list[Note] | None = None
        self._grab_cursor = self._make_cursor("grab")
        self._grabbing_cursor = self._make_cursor("grabbing")

        self.add_css_class("fan")
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(10)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.add_css_class("fan-header")
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label=strings.NOTES_HEADER)
        title.set_xalign(0)
        title.set_hexpand(True)
        title.add_css_class("header")
        bar.append(title)

        new = Gtk.Button(label=strings.NEW_NOTE_LABEL)
        new.set_tooltip_text(strings.NEW_NOTE)
        new.connect("clicked", lambda _button: on_new())
        bar.append(new)
        self.new_button = new

        # Spec §6.2/§7.3: the header × has to work without keyboard focus,
        # because hovering the deck never takes focus and Esc cannot arrive.
        close = Gtk.Button(label=strings.CLOSE)
        close.set_tooltip_text(strings.COLLAPSE_DECK)
        close.connect("clicked", lambda _button: on_collapse())
        bar.append(close)
        self.close_button = close

        hint = Gtk.Label(label=strings.FAN_HINT)
        hint.set_xalign(0)
        hint.set_ellipsize(Pango.EllipsizeMode.END)
        hint.add_css_class("hint")
        bar.set_margin_bottom(2)
        header.append(bar)
        header.append(hint)
        self.append(header)

        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        # Start-aligned so tabs keep their natural height; a short deck must
        # not stretch its tabs to fill the fan.
        self.rows.set_valign(Gtk.Align.START)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_child(self.rows)
        self.scroller = scroller
        self.append(scroller)

        # Fixed peek pane: always allocated, even while empty. The tab list
        # shrinks/scrolls inside its own viewport, so a peek can never change
        # tab geometry or slide another tab under the pointer.
        self.peek_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.peek_pane.add_css_class("peek-pane")
        self.peek_pane.set_size_request(-1, PEEK_PANE_HEIGHT)
        self.peek_hint = Gtk.Label(label=strings.PEEK_HINT)
        self.peek_hint.set_xalign(0)
        self.peek_hint.add_css_class("hint")
        self.peek_pane.append(self.peek_hint)
        self.append(self.peek_pane)

        # The scroller already routes wheel events to its adjustment; this
        # signal only refreshes the smoke-test snapshot after a scroll.
        scroller.get_vadjustment().connect("value-changed", self._on_value_changed)
        # Wheel over the peek pane must still scroll the tab list.
        peek_scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        peek_scroll.connect("scroll", self._on_peek_scroll)
        self.peek_pane.add_controller(peek_scroll)

    def set_notes(self, notes: Sequence[Note]) -> None:
        """Rebuild the tabs from *notes* — unless a drag is in flight.

        A rebuild during a gesture would destroy the button that owns the
        active ``Gtk.GestureDrag`` and lose the press. Calls that arrive while
        a press/drag is live are parked and applied on the next idle after the
        gesture ends.
        """
        pending = list(notes)
        if self._drag is not None:
            self._pending_notes = pending
            return
        self._install_notes(pending)

    def _install_notes(self, notes: Sequence[Note]) -> None:
        self.hide_peek()
        self._tabs.clear()
        self._tab_order.clear()
        while (child := self.rows.get_first_child()) is not None:
            self.rows.remove(child)

        if not notes:
            empty = Gtk.Label(label=strings.NO_NOTES)
            empty.set_xalign(0)
            empty.add_css_class("empty")
            self.rows.append(empty)
            return

        for note in notes:
            button = Gtk.Button()
            button.add_css_class("tab")
            button.set_hexpand(True)
            button.set_cursor(self._grab_cursor)
            label = Gtk.Label(label=note.title())
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(label)
            motion = Gtk.EventControllerMotion()
            motion.connect(
                "enter", lambda _c, _x, _y, note_id=note.id: self._on_hover_tab(note_id)
            )
            motion.connect(
                "leave", lambda _c, note_id=note.id: self._on_leave_tab(note_id)
            )
            button.add_controller(motion)

            # Spec §7.2 / PLATFORM §8: one gesture, no GestureClick. It starts
            # on press; the session decides on the release whether the offset
            # was a click (<5 px) or a drag.
            drag = Gtk.GestureDrag()
            drag.connect(
                "drag-begin",
                lambda g, x, y, b=button, note_id=note.id: self._drag_begin(
                    g, b, note_id, x, y
                ),
            )
            drag.connect("drag-update", self._drag_update)
            drag.connect("drag-end", self._drag_end)
            drag.connect("cancel", self._drag_cancel)
            button.add_controller(drag)

            self.rows.append(button)
            self._tabs[note.id] = button
            self._tab_order.append(note.id)

    # -- drag reorder --------------------------------------------------

    def _drag_begin(
        self,
        _gesture: Gtk.GestureDrag,
        button: Gtk.Button,
        note_id: str,
        x: float,
        y: float,
    ) -> None:
        if self._drag is not None:
            # A stale session (gesture cancelled without a signal) must not
            # leak its raised style into the next press.
            self._clear_drag_visuals()
        if note_id not in self._tab_order:
            return
        self._drag = DragSession(note_id, self._tab_order.index(note_id))
        self._drag_button = button
        self._drag_start = self._point_in_page(button, x, y)
        self._drag_target = None
        # Make the press session observable in the test dump before the 5 px
        # threshold; it is also how the smoke tells "press reached the tab"
        # from "a foreign pointer grab swallowed the click".
        if self._on_drag_update is not None:
            self._on_drag_update()

    def _drag_update(
        self, _gesture: Gtk.GestureDrag, dx: float, dy: float
    ) -> None:
        session = self._drag
        if session is None or self._drag_button is None:
            return
        was_active = session.active
        if not session.update(dx, dy):
            return
        if not was_active:
            self._drag_button.add_css_class("dragging")
            self._drag_button.set_cursor(self._grabbing_cursor)
            if self._on_drag_begin is not None:
                self._on_drag_begin(session.note_id)
        target = target_index(self._release_y(dy), self._row_spans())
        if target != self._drag_target:
            self._drag_target = target
            if self._on_drag_update is not None:
                self._on_drag_update()

    def _drag_end(self, _gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        session = self._drag
        if session is None:
            return
        start = self._drag_start
        release_x, release_y = (
            (start[0] + dx, start[1] + dy)
            if start is not None
            else (dx, dy)
        )
        button = self._drag_button
        inside = self._inside_deck(release_x, release_y)
        on_tab = button is not None and self._inside_widget(
            button, release_x, release_y
        )
        result = session.finish(
            released_inside=inside,
            released_on_tab=on_tab,
            pointer_y=release_y,
            spans=self._row_spans(),
        )
        self._finish_drag()
        if self._on_drag_end is not None:
            self._on_drag_end()
        if result.kind == CLICK:
            # Leave the gesture's signal emission before any widget rebuild.
            GLib.idle_add(self._open_idle, result.note_id)
        elif (
            result.kind == REORDER
            and result.target is not None
            and result.target != result.source
        ):
            GLib.idle_add(self._reorder_idle, result.note_id, result.target)

    def _drag_cancel(self, _gesture: Gtk.GestureDrag, _sequence) -> None:
        if self._drag is None:
            return
        self._finish_drag()
        if self._on_drag_end is not None:
            self._on_drag_end()

    def _finish_drag(self) -> None:
        self._clear_drag_visuals()
        self._drag = None
        self._drag_button = None
        self._drag_start = None
        self._drag_target = None
        if self._pending_notes is not None:
            notes, self._pending_notes = self._pending_notes, None
            GLib.idle_add(self._install_notes_idle, notes)

    def _clear_drag_visuals(self) -> None:
        if self._drag_button is not None:
            self._drag_button.remove_css_class("dragging")
            self._drag_button.set_cursor(self._grab_cursor)

    def _open_idle(self, note_id: str) -> bool:
        self._on_open(note_id)
        return False

    def _reorder_idle(self, note_id: str, target: int) -> bool:
        self._on_reorder(note_id, target)
        return False

    def _install_notes_idle(self, notes: Sequence[Note]) -> bool:
        self._install_notes(notes)
        return False

    def _release_y(self, dy: float) -> float:
        return (self._drag_start[1] if self._drag_start is not None else 0.0) + dy

    def _row_spans(self) -> list[tuple[float, float]]:
        """The rendered vertical span of every tab, in fan coordinates."""
        spans: list[tuple[float, float]] = []
        for note_id in self._tab_order:
            found, bounds = self._tabs[note_id].compute_bounds(self)
            if not found:
                return []
            spans.append((bounds.get_y(), bounds.get_y() + bounds.get_height()))
        return spans

    def _inside_page(self, x: float, y: float) -> bool:
        return 0 <= x < self.get_width() and 0 <= y < self.get_height()

    def _inside_deck(self, x: float, y: float) -> bool:
        """Release-point test in the panel window, not just the fan content.

        The fan's margins and the status banner are still inside the deck; the
        10 px strip is a separate window and is not a drop target. With no root
        (unit context) the page bounds are the best available answer.
        """
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            window_x, window_y = self._point_in(self, root, x, y)
            return (
                0 <= window_x < root.get_width()
                and 0 <= window_y < root.get_height()
            )
        return self._inside_page(x, y)

    def _inside_widget(self, widget: Gtk.Widget, x: float, y: float) -> bool:
        found, bounds = widget.compute_bounds(self)
        if not found:
            return False
        return (
            bounds.get_x() <= x <= bounds.get_x() + bounds.get_width()
            and bounds.get_y() <= y <= bounds.get_y() + bounds.get_height()
        )

    def _point_in_page(
        self, widget: Gtk.Widget, x: float, y: float
    ) -> tuple[float, float]:
        return self._point_in(widget, self, x, y)

    @staticmethod
    def _point_in(
        source: Gtk.Widget, target: Gtk.Widget, x: float, y: float
    ) -> tuple[float, float]:
        point = Graphene.Point()
        point.x = x
        point.y = y
        result = source.compute_point(target, point)
        if isinstance(result, tuple):
            result = result[1]
        return result.x, result.y

    @staticmethod
    def _make_cursor(name: str) -> Gdk.Cursor | None:
        try:
            return Gdk.Cursor.new_from_name(name, None)
        except GLib.Error:
            return None

    # -- peek ----------------------------------------------------------

    def show_peek(self, note_id: str, lines: Sequence[str]) -> None:
        """Show up to six read-only body lines in the fixed in-fan pane."""
        if note_id not in self._tabs:
            self.hide_peek()
            return
        self._clear_peek_pane()
        if lines:
            for line in lines[:PREVIEW_LINES]:
                label = Gtk.Label(label=line)
                label.set_xalign(0)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.add_css_class("peek-line")
                self.peek_pane.append(label)
            self.peek_hint.set_visible(False)
        else:
            self.peek_hint.set_text(strings.PEEK_EMPTY)
            self.peek_hint.set_visible(True)
        self._peek_note = note_id
        self._peek_lines = list(lines[:PREVIEW_LINES])

    def hide_peek(self) -> None:
        self._clear_peek_pane()
        self.peek_hint.set_text(strings.PEEK_HINT)
        self.peek_hint.set_visible(True)
        self._peek_note = None
        self._peek_lines = []

    def peek_snapshot(self) -> dict:
        return {
            "id": self._peek_note,
            "lines": list(self._peek_lines),
            "rendered": self._rendered_peek_lines(),
            "visible": [self._peek_note] if self._peek_note else [],
        }

    def peek_center(self, relative_to: Gtk.Widget | None = None) -> list[float] | None:
        found, bounds = self.peek_pane.compute_bounds(relative_to or self)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def _rendered_peek_lines(self) -> list[str]:
        rendered: list[str] = []
        child = self.peek_pane.get_first_child()
        while child is not None:
            if child is not self.peek_hint and isinstance(child, Gtk.Label):
                rendered.append(child.get_text())
            child = child.get_next_sibling()
        return rendered

    def _clear_peek_pane(self) -> None:
        """Remove every peek row, keeping the fixed hint label."""
        child = self.peek_pane.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            if child is not self.peek_hint:
                self.peek_pane.remove(child)
            child = following

    def _on_peek_scroll(self, _controller, _dx, dy) -> bool:
        self.scroller.get_vadjustment().set_value(
            self.scroller.get_vadjustment().get_value() + dy * 60
        )
        return True

    # -- geometry / smoke hooks ---------------------------------------

    def tab_centers(self, relative_to: Gtk.Widget | None = None) -> list[list[float]]:
        """Tab centres in *relative_to* (default: this page) for smoke clicks."""
        centers: list[list[float]] = []
        target = relative_to if relative_to is not None else self
        child = self.rows.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                found, bounds = child.compute_bounds(target)
                if found:
                    centers.append(
                        [
                            bounds.get_x() + bounds.get_width() / 2,
                            bounds.get_y() + bounds.get_height() / 2,
                        ]
                    )
            child = child.get_next_sibling()
        return centers

    def tab_center(
        self, note_id: str, relative_to: Gtk.Widget | None = None
    ) -> list[float] | None:
        """One tab's centre, or None when it is not in the current layout."""
        tab = self._tabs.get(note_id)
        if tab is None:
            return None
        found, bounds = tab.compute_bounds(relative_to or self)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def tab_heights(self) -> list[int]:
        """Logical tab heights; wheel scrolling must not change them."""
        heights: list[int] = []
        for note_id in self._tab_order:
            found, bounds = self._tabs[note_id].compute_bounds(self)
            heights.append(round(bounds.get_height()) if found else 0)
        return heights

    def new_button_center(self) -> list[float] | None:
        return self._center_of(self.new_button)

    def collapse_button_center(self) -> list[float] | None:
        return self._center_of(self.close_button)

    def scroll_value(self) -> float:
        return self.scroller.get_vadjustment().get_value()

    def scroll_by(self, delta: float) -> None:
        """Move the tab list without a pointer (keyboard/test activation)."""
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_value() + delta)

    def activate_tab(self, note_id: str) -> None:
        """Activate a tab as a click would (used by the smoke control hook)."""
        if note_id in self._tabs:
            self._on_open(note_id)

    def activate_collapse(self) -> None:
        self.close_button.emit("clicked")

    # -- drag state / smoke hooks --------------------------------------

    def drag_snapshot(self) -> dict:
        """Observable drag state for the test dump and ticket 10.

        ``raised`` is the CSS class that lifts the tab (spec §6.5) and
        ``cursor`` is read back from the widget, so a smoke test proves both
        the style and the ``grab`` -> ``grabbing`` swap, not just intent.
        """
        session = self._drag
        active = session is not None and session.active
        button = self._drag_button
        cursor = None
        if button is not None:
            current = button.get_cursor()
            cursor = current.get_name() if current is not None else None
        return {
            "pressed": session is not None,
            "active": active,
            "note_id": session.note_id if session is not None else None,
            "source_index": session.source if session is not None else -1,
            "target_index": self._drag_target if active else None,
            "raised": bool(
                active and button is not None and button.has_css_class("dragging")
            ),
            "cursor": cursor if active else None,
        }

    def tab_ids(self) -> list[str]:
        """Rendered tab order (the note array as the fan built it)."""
        return list(self._tab_order)

    def tab_titles(self) -> list[str]:
        """Rendered tab labels, in widget order."""
        titles: list[str] = []
        for note_id in self._tab_order:
            label = self._tabs[note_id].get_child()
            if isinstance(label, Gtk.Label):
                titles.append(label.get_text())
        return titles

    def tab_cursors(self) -> list[str | None]:
        """Cursor names currently set on the tabs; ``grab`` when idle."""
        names: list[str | None] = []
        for note_id in self._tab_order:
            cursor = self._tabs[note_id].get_cursor()
            names.append(cursor.get_name() if cursor is not None else None)
        return names

    def _center_of(self, widget: Gtk.Widget) -> list[float] | None:
        found, bounds = widget.compute_bounds(self)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]

    def _on_value_changed(self, _adjustment) -> None:
        if self._on_scrolled is not None:
            self._on_scrolled()
