"""Test-only plumbing, kept out of the production application module.

Everything here is env-gated and does nothing unless the corresponding
``LURKNOTES_TEST_*`` variable is set. The smokes start their own isolated
instance and use these hooks only to observe or drive the real widgets.

``LURKNOTES_TEST_DUMP``
    Write a JSON snapshot of the deck to this path after mapping and after
    opening a note. Includes fan/rail centres so the smoke can click through
    X11, and peek state so a crossing can be checked for a blank pane.
``LURKNOTES_TEST_TYPE``
    Append this text to the open note shortly after it opens, as if typed.
``LURKNOTES_TEST_CONTROL``
    Register the ``control`` GAction the smoke uses when another agent's
    ``ABOVE`` window owns the screen edge. Off in production: no extra action
    and no polling.
``LURKNOTES_TEST_PIN_DECK``
    Do not collapse the fan when the pointer leaves, so an unrelated pointer
    warp cannot hide the panel mid-test.
``LURKNOTES_TEST_REFUSE_FOCUS``
    Pretend activation was refused so a smoke can prove the "Click to type"
    hint and the first-click grant where ``present()`` normally succeeds.
``LURKNOTES_TEST_NO_HOVER``
    Ignore pointer-enter events, proving that a bare ``lurknotes`` expands the
    fan itself even when the shared pointer moves elsewhere.
``LURKNOTES_TEST_UNDO_MS``
    Shorten the 10 s undo window. Production always uses ``UNDO_TIMEOUT_MS``.

``LURKNOTES_TEST_OPEN_ALL`` was removed: smokes open All Notes through the real
``lurknotes all`` command instead of a second startup path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from gi.repository import Gio, GLib

from .undo import UNDO_TIMEOUT_MS


def undo_timeout_ms() -> int:
    """The undo window, shortened only by the explicit smoke-test hook."""
    raw = os.environ.get("LURKNOTES_TEST_UNDO_MS")
    if not raw:
        return UNDO_TIMEOUT_MS
    try:
        value = int(raw)
    except ValueError:
        return UNDO_TIMEOUT_MS
    return value if value > 0 else UNDO_TIMEOUT_MS


def _flag(name: str) -> bool:
    return os.environ.get(name) == "1"


class TestHooks:
    """Snapshot writer, control channel and deterministic input for smokes."""

    def __init__(self, app) -> None:
        self.app = app
        self.dump_path = os.environ.get("LURKNOTES_TEST_DUMP")
        self.type_text = os.environ.get("LURKNOTES_TEST_TYPE")
        self.typed = False
        self.pin_deck = _flag("LURKNOTES_TEST_PIN_DECK")
        self.no_hover = _flag("LURKNOTES_TEST_NO_HOVER")
        self.refuse_focus = _flag("LURKNOTES_TEST_REFUSE_FOCUS")
        self.control_enabled = bool(os.environ.get("LURKNOTES_TEST_CONTROL"))

    def install_control_action(self) -> None:
        if not self.control_enabled:
            return
        control = Gio.SimpleAction.new("control", GLib.VariantType.new("s"))
        control.connect("activate", self._on_control)
        self.app.add_action(control)

    def schedule_dump(self, delay: int = 150) -> None:
        if self.dump_path:
            GLib.timeout_add(delay, self.write_dump)

    def write_dump(self) -> bool:
        app = self.app
        if not self.dump_path or app.panel is None:
            return False

        state = app.state
        is_open = state == "open"
        is_fan = state == "fan"
        peek = app.panel.peek_snapshot()
        peek["center"] = app.panel.peek_center() if is_fan else None
        snapshot = {
            "state": state,
            "current_id": app.current_id,
            "ids": [note.id for note in app.notes],
            "titles": [note.title() for note in app.notes],
            "tab_centers": app.panel.tab_centers() if is_fan else [],
            "tab_heights": app.panel.tab_heights() if is_fan else [],
            "tab_ids": app.panel.tab_ids(),
            "tab_titles": app.panel.tab_titles(),
            "tab_cursors": app.panel.tab_cursors(),
            "drag": app.panel.drag_snapshot(),
            "new_button_center": (
                app.panel.new_button_center() if is_fan else None
            ),
            "collapse_button_center": (
                app.panel.collapse_button_center() if is_fan else None
            ),
            "scroll_value": app.panel.scroll_value(),
            "peek": peek,
            "rail_centers": app.panel.rail_centers() if is_open else [],
            "rail_titles": app.panel.rail_titles() if is_open else [],
            "active_index": app.panel.active_index() if is_open else -1,
            "text": app.panel.note.text() if is_open else None,
            "cursor_offset": (
                app.panel.note.cursor_offset() if is_open else None
            ),
            "cursor_at_end": (
                app.panel.note.cursor_at_end() if is_open else None
            ),
            "rail_width": app.panel.note.rail_width() if is_open else None,
            "typed": self.typed,
            "read_only": app.read_only,
            "overwrite_blocked": app.overwrite_blocked,
            "unsaved": app.unsaved,
            "status": app.panel.status_snapshot(),
            "all_notes": (
                app.all_notes.snapshot() if app.all_notes is not None else None
            ),
            "toast": app.panel.toast_snapshot(),
            "undo_pending": app._undo.pending is not None,
            "panel_focused": app._panel_has_focus(),
            "focus_hint": app.panel.focus_hint_snapshot(),
            "onboarding": app.panel.onboarding_snapshot(),
            "last_command": getattr(app, "_last_command", ""),
        }
        target = Path(self.dump_path)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(json.dumps(snapshot), encoding="utf-8")
            os.replace(temporary, target)
        except OSError:
            pass
        return False

    def maybe_type(self) -> bool:
        app = self.app
        if not self.type_text or self.typed or app.state != "open":
            return False
        self.typed = True
        app.panel.note.insert_at_cursor(self.type_text)
        self.schedule_dump(delay=30)
        return False

    def _on_control(self, _action, parameter) -> None:
        """Drive deck interactions when another test covers the screen.

        Only registered with ``LURKNOTES_TEST_CONTROL``. It calls the same
        handlers the X11 pointer would (motion controllers, button ``clicked``
        signals), so the state machine and widgets are exercised even when a
        concurrent agent's ABOVE window owns the pixels at the screen edge.
        """
        app = self.app
        command = parameter.get_string() if parameter is not None else ""
        if command == "strip":
            app._on_deck_enter()
        elif command == "leave":
            app._on_deck_leave()
        elif command.startswith("tab:"):
            app._on_tab_enter(command[4:])
        elif command.startswith("untab:"):
            app._on_tab_leave(command[6:])
        elif command == "header":
            if app.panel is not None:
                app.panel.activate_collapse()
        elif command.startswith("tabclick:"):
            if app.panel is not None:
                app.panel.activate_tab(command[9:])
        elif command.startswith("scroll:"):
            if app.panel is not None:
                app.panel.scroll_by(float(command[7:]))
        elif command.startswith("open:"):
            app.open_note(command[5:])
        elif command == "close":
            app.close_note()
        elif command == "undo":
            app.undo_delete()
        else:
            print(f"lurknotes: unknown test control {command!r}", file=sys.stderr)
