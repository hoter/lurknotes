"""The All Notes window: a normal window with search over the whole deck.

Spec §6.4: 720 × 560 by default, resizable, search and a menu at the top, a
row per note (title, snippet, updated date) in manual deck order. Clicking a
row opens the note in the edge panel and leaves this window mapped.

Unlike the strip and panel this is an ordinary window: it stays decorated, is
allowed to take focus, and must appear in the dock and Alt+Tab (spec §9.1).
"""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Gio, GLib, Gtk, Pango

from .. import strings
from ..all_notes import (
    AllNotesModel,
    SearchHit,
    format_updated,
    highlight_markup,
)
from ..events import DeckChanged
from ..notes import Note

WIDTH = 720
HEIGHT = 560


class AllNotesWindow(Gtk.Window):
    """Read-only list of the deck with a live, case-insensitive search."""

    def __init__(
        self,
        application: Gtk.Application,
        *,
        notes_provider: Callable[[], Sequence[Note]],
        on_open: Callable[[str], None],
        events: DeckChanged,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(application=application, title=strings.ALL_NOTES_TITLE)
        self._on_open = on_open
        self._events = events
        self._on_refresh = on_refresh
        self._refresh_scheduled = False
        self._row_buttons: list[Gtk.Button] = []
        self.model = AllNotesModel(notes_provider)

        self.set_default_size(WIDTH, HEIGHT)
        self.set_resizable(True)
        self.add_css_class("lurk")
        self.add_css_class("all-notes")

        header = Gtk.HeaderBar()
        header.add_css_class("all-notes-header")
        title = Gtk.Label(label=strings.ALL_NOTES_TITLE)
        title.add_css_class("header")
        header.pack_start(title)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(strings.ALL_NOTES_SEARCH)
        self.search.set_hexpand(True)
        self.search.connect("search-changed", self._on_search_changed)
        header.set_title_widget(self.search)

        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_icon_name("open-menu-symbolic")
        self.menu_button.set_tooltip_text(strings.ALL_NOTES_MENU)
        self.menu_button.add_css_class("all-notes-menu")
        menu = Gio.Menu()
        # The existing app.quit action runs the shutdown flush/save cleanup.
        menu.append(strings.QUIT, "app.quit")
        self.menu_button.set_menu_model(menu)
        header.pack_end(self.menu_button)
        self.set_titlebar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("all-notes-body")
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.rows.set_margin_top(10)
        self.rows.set_margin_bottom(10)
        self.rows.set_margin_start(12)
        self.rows.set_margin_end(12)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_child(self.rows)
        body.append(scroller)
        self.set_child(body)

        events.subscribe(self._on_deck_changed)
        self.connect("close-request", self._on_close_request)
        self.connect("destroy", self._on_destroy)

    # -- showing / refreshing ------------------------------------------

    def refresh(self) -> list[SearchHit]:
        hits = self.model.refresh()
        self._render(hits)
        return hits

    def focus_search(self) -> None:
        self.search.grab_focus()

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._render(self.model.set_query(self.search.get_text()))

    def _on_deck_changed(self) -> None:
        # Coalesce a burst of edits (one per keystroke) into one idle rebuild.
        if not self.get_visible() or self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        GLib.idle_add(self._refresh_idle)

    def _refresh_idle(self) -> bool:
        self._refresh_scheduled = False
        self.refresh()
        return False

    def _on_close_request(self, *_args) -> bool:
        # Closing All Notes is not quitting LurkNotes: the strip stays alive.
        self.set_visible(False)
        return True

    def _on_destroy(self, *_args) -> None:
        self._events.unsubscribe(self._on_deck_changed)

    # -- rendering -----------------------------------------------------

    def _render(self, hits: Sequence[SearchHit]) -> None:
        while (child := self.rows.get_first_child()) is not None:
            self.rows.remove(child)
        self._row_buttons = []

        if not hits:
            empty = Gtk.Label(
                label=(
                    strings.ALL_NOTES_NO_MATCH
                    if self.model.query.strip()
                    else strings.ALL_NOTES_EMPTY
                )
            )
            empty.set_xalign(0)
            empty.add_css_class("all-notes-empty")
            self.rows.append(empty)
            if self._on_refresh is not None:
                self._on_refresh()
            return

        for hit in hits:
            self.rows.append(self._row(hit))

        if self._on_refresh is not None:
            self._on_refresh()

    def _row(self, hit: SearchHit) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("all-notes-row")
        button.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_hexpand(True)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)

        title = Gtk.Label(label=hit.note.title())
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("all-notes-title")
        text.append(title)

        snippet = Gtk.Label()
        snippet.set_xalign(0)
        snippet.set_ellipsize(Pango.EllipsizeMode.END)
        snippet.add_css_class("all-notes-snippet")
        if hit.highlight is not None:
            snippet.set_markup(highlight_markup(hit.snippet, hit.highlight))
        else:
            snippet.set_text(hit.snippet)
        text.append(snippet)
        box.append(text)

        date = Gtk.Label(label=format_updated(hit.note.updated))
        date.set_xalign(1)
        date.set_valign(Gtk.Align.START)
        date.add_css_class("all-notes-date")
        box.append(date)

        button.set_child(box)
        button.connect(
            "clicked", lambda _button, note_id=hit.note.id: self._on_open(note_id)
        )
        self._row_buttons.append(button)
        return button

    # -- test hooks ----------------------------------------------------

    def snapshot(self) -> dict:
        """State and clickable centres for the live X11 smoke."""
        row_centers: list[list[float] | None] = []
        for row in self._row_buttons:
            found, bounds = row.compute_bounds(self)
            if found:
                row_centers.append(
                    [
                        bounds.get_x() + bounds.get_width() / 2,
                        bounds.get_y() + bounds.get_height() / 2,
                    ]
                )
            else:
                row_centers.append(None)

        return {
            "visible": self.get_visible(),
            "mapped": self.get_mapped(),
            "width": self.get_width(),
            "height": self.get_height(),
            "resizable": self.get_resizable(),
            "decorated": self.get_decorated(),
            "query": self.search.get_text(),
            "ids": [hit.note.id for hit in self.model.hits],
            "titles": [hit.note.title() for hit in self.model.hits],
            "snippets": [hit.snippet for hit in self.model.hits],
            "markups": [
                highlight_markup(hit.snippet, hit.highlight)
                for hit in self.model.hits
            ],
            "dates": [
                format_updated(hit.note.updated) for hit in self.model.hits
            ],
            "row_centers": row_centers,
            "search_center": self._center(self.search),
            "menu_center": self._center(self.menu_button),
        }

    def _center(self, widget: Gtk.Widget) -> list[float] | None:
        found, bounds = widget.compute_bounds(self)
        if not found:
            return None
        return [
            bounds.get_x() + bounds.get_width() / 2,
            bounds.get_y() + bounds.get_height() / 2,
        ]
