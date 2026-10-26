"""The fan: tabs for every note, in array order (spec §6.2).

Each tab is a plain ``Gtk.Button`` with a title label and a per-tab motion
controller. The read-only peek is a separate no-focus window placed next to the
hovered tab (``windows/peek.py``), so showing or hiding it never changes tab
heights or positions: crossing tabs cannot slide another tab under the pointer.
Ticket 06 replaces the button's ``clicked`` handler with one ``GestureDrag`` on
this same widget; the motion controllers stay as they are.
"""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gtk, Pango

from .. import strings
from ..notes import Note


class FanPage(Gtk.Box):
    """Read-only list of note tabs. Clicking a tab opens its note."""

    def __init__(
        self,
        on_open: Callable[[str], None],
        on_new: Callable[[], None],
        on_collapse: Callable[[], None],
        on_hover_tab: Callable[[str], None],
        on_leave_tab: Callable[[str], None],
        on_scrolled: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_open = on_open
        self._on_collapse = on_collapse
        self._on_hover_tab = on_hover_tab
        self._on_leave_tab = on_leave_tab
        self._on_scrolled = on_scrolled
        self._tabs: dict[str, Gtk.Button] = {}
        self._tab_order: list[str] = []

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

        # The scroller already routes wheel events to its adjustment; this
        # signal only refreshes the smoke-test snapshot after a scroll.
        scroller.get_vadjustment().connect("value-changed", self._on_value_changed)

    def set_notes(self, notes: Sequence[Note]) -> None:
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
            label = Gtk.Label(label=note.title())
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(label)
            button.connect(
                "clicked", lambda _button, note_id=note.id: self._on_open(note_id)
            )
            motion = Gtk.EventControllerMotion()
            motion.connect(
                "enter", lambda _c, _x, _y, note_id=note.id: self._on_hover_tab(note_id)
            )
            motion.connect(
                "leave", lambda _c, note_id=note.id: self._on_leave_tab(note_id)
            )
            button.add_controller(motion)

            self.rows.append(button)
            self._tabs[note.id] = button
            self._tab_order.append(note.id)

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
        tab = self._tabs.get(note_id)
        if tab is not None:
            tab.emit("clicked")

    def activate_collapse(self) -> None:
        self.close_button.emit("clicked")

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
