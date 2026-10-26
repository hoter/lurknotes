#!/usr/bin/env python3
"""PROTOTYPE — throwaway code for ticket 05 (deck at the edge on GNOME 46).

Question this answers: does the deck-at-the-edge feel right, and does an
XWayland window actually stay above other windows and out of the dock?

This is NOT production code: no tests, no error handling beyond "it runs",
no abstractions. Delete it once the verdict is recorded.

Run:  python3 .scratch/edge-notes/prototype/edge_notes.py
Quit: Ctrl+Q
"""

import os

os.environ["GDK_BACKEND"] = "x11"

import ctypes
import json
import time
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk, Pango

APP_ID = "dev.edgenotes.Prototype"
DATA_FILE = Path.home() / ".local/share/edge-notes/notes.json"

PANEL_W = 380          # logical px
STRIP_W = 10           # logical px, always visible
SHOW_DELAY_MS = 100
HIDE_CHECK_MS = 160
SAVE_DEBOUNCE_MS = 400
UNDO_MS = 10_000
ROW_H = 44
PEEK_DELAY_MS = 150

CSS = """
.strip { background: #24242c; border-left: 1px solid #3d3d49; }
window.panel, .panel { background-color: #1c1c22; color: #e9e9f1; }
.panel scrolledwindow, .panel viewport { background-color: transparent; }
.header { color: #8d8d9c; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
.tab { background: #2b2b35; border-radius: 10px; padding: 7px 10px; border: 1px solid #343440; }
.tab:hover { background: #353542; }
.tab-drag { background: #3d3d4c; box-shadow: 0 10px 24px rgba(0, 0, 0, 0.55); }
.tab-title { color: #ececf3; font-weight: 600; }
.preview { color: #a9a9b8; font-size: 11px; }
.rail { background: #17171d; border-right: 1px solid #2a2a34; }
.railbtn { background: transparent; border-radius: 6px; padding: 4px 6px; color: #b9b9c6; font-size: 11px; }
.railbtn:hover { background: #26262f; }
.railbtn-active { background: #30303c; color: #ffffff; }
.editor, .editor text { background: #1c1c22; color: #e9e9f1; font-size: 13px; }
.toast { background: #3a3a46; color: #ffffff; border-radius: 8px; padding: 6px 10px; }
.empty { color: #6c6c7a; font-size: 12px; }
.hint { color: #6f6f7e; font-size: 10px; }
"""


# ---------------------------------------------------------------- X11 plumbing


class _Msg(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _Ev(ctypes.Union):
    _fields_ = [("c", _Msg), ("pad", ctypes.c_long * 24)]


class _WMHints(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_long),
        ("input", ctypes.c_int),
        ("initial_state", ctypes.c_int),
        ("icon_pixmap", ctypes.c_ulong),
        ("icon_window", ctypes.c_ulong),
        ("icon_x", ctypes.c_int),
        ("icon_y", ctypes.c_int),
        ("icon_mask", ctypes.c_ulong),
        ("window_group", ctypes.c_ulong),
    ]


class X11:
    def __init__(self):
        L = ctypes.CDLL("libX11.so.6")
        self.L = L
        L.XOpenDisplay.restype = ctypes.c_void_p
        L.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.dpy = L.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("no X display")
        L.XDefaultRootWindow.restype = ctypes.c_ulong
        L.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.root = L.XDefaultRootWindow(self.dpy)
        L.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.XDisplayWidth.restype = ctypes.c_int
        self.root_w = L.XDisplayWidth(self.dpy, 0)
        L.XInternAtom.restype = ctypes.c_ulong
        L.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint,
        ]
        L.XMoveResizeWindow.restype = ctypes.c_int
        L.XSendEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
            ctypes.c_void_p,
        ]
        L.XQueryPointer.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        L.XQueryPointer.restype = ctypes.c_int
        L.XFlush.argtypes = [ctypes.c_void_p]
        L.XSetWMHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_WMHints)]
        L.XSetWMHints.restype = ctypes.c_int
        L.XChangeProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
        ]
        L.XChangeProperty.restype = ctypes.c_int
        L.XDeleteProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        L.XDeleteProperty.restype = ctypes.c_int

    def atom(self, name):
        return self.L.XInternAtom(self.dpy, name.encode(), 0)

    def flush(self):
        self.L.XFlush(self.dpy)

    def move_resize(self, xid, x, y, w, h):
        self.L.XMoveResizeWindow(self.dpy, xid, int(x), int(y), int(w), int(h))
        self.flush()

    def client_message(self, xid, mtype, d0, d1=0):
        ev = _Ev()
        ev.c.type = 33  # ClientMessage
        ev.c.send_event = 1
        ev.c.display = self.dpy
        ev.c.window = xid
        ev.c.message_type = mtype
        ev.c.format = 32
        ev.c.data[0] = d0
        ev.c.data[1] = d1
        mask = (1 << 20) | (1 << 19)  # SubstructureNotify | SubstructureRedirect
        self.L.XSendEvent(self.dpy, self.root, 0, mask, ctypes.byref(ev))
        self.flush()

    def set_hints(self, xid):
        state = self.atom("_NET_WM_STATE")
        for prop in (
            "_NET_WM_STATE_ABOVE",
            "_NET_WM_STATE_SKIP_TASKBAR",
            "_NET_WM_STATE_STICKY",
        ):
            self.client_message(xid, state, 1, self.atom(prop))
        self.client_message(xid, self.atom("_NET_WM_DESKTOP"), 0xFFFFFFFF)

    def set_input(self, xid, on):
        """WM_HINTS.input — off keeps hover-mapping from stealing keyboard focus."""
        hints = _WMHints()
        hints.flags = 1  # InputHint
        hints.input = 1 if on else 0
        self.L.XSetWMHints(self.dpy, xid, ctypes.byref(hints))
        self.flush()

    def set_no_focus(self, xid):
        """EWMH: user time 0 asks the WM not to focus the window when it maps."""
        value = (ctypes.c_long * 1)(0)
        self.L.XChangeProperty(
            self.dpy, xid, self.atom("_NET_WM_USER_TIME"), 6,  # XA_CARDINAL
            32, 0, ctypes.cast(value, ctypes.c_void_p), 1,
        )
        self.flush()

    def allow_focus(self, xid):
        self.L.XDeleteProperty(self.dpy, xid, self.atom("_NET_WM_USER_TIME"))
        self.flush()

    def pointer(self):
        rr, cr = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        ok = self.L.XQueryPointer(
            self.dpy, self.root, ctypes.byref(rr), ctypes.byref(cr),
            ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx),
            ctypes.byref(wy), ctypes.byref(mask),
        )
        return (rx.value, ry.value) if ok else None


# ---------------------------------------------------------------- tiny store


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:60]
    return "Untitled"


def preview_text(text):
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[1:7]) or "…"


class Store:
    def __init__(self, path):
        self.path = path
        self.notes = []
        self.load()

    def load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.notes = data.get("notes", [])
                return
            except (OSError, ValueError):
                pass
        now = time.time()
        self.notes = [
            {"id": str(uuid.uuid4()), "text": "Groceries\nmilk\neggs\nbread", "created": now, "updated": now},
            {"id": str(uuid.uuid4()), "text": "Standup\nwhat I did\nwhat I will do\nblockers", "created": now, "updated": now},
            {"id": str(uuid.uuid4()), "text": "Ideas\nnotes at the edge of the screen", "created": now, "updated": now},
        ]
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "notes": self.notes}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        if self.path.exists():
            (self.path.parent / "notes.bak.json").write_text(self.path.read_text())
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- the app


class EdgeNotes(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.store = Store(DATA_FILE)
        self.x11 = X11()
        self.state = "strip"          # strip | fan | open
        self.current = None
        self.monitor_h = 960
        self.hide_source = 0
        self.show_source = 0
        self.save_source = 0
        self.undo_source = 0
        self.pending = None           # (note, index) waiting for undo
        self._loading = False
        self.panel_h = None
        self.strip_h = None
        self.scale = 1.0

    # -- lifecycle -------------------------------------------------------

    def do_activate(self):
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        self.monitor_h = (
            Gdk.Display.get_default().get_monitors().get_item(0).get_geometry().height
        )
        self.apply_css()
        self.build_strip()
        self.build_panel()
        self.rebuild_fan()
        self.rebuild_rail()

        # Realize first, then mark the windows as not taking focus, then map:
        # a window that maps with input=True yanks keyboard focus from whatever
        # the user is typing in.
        for win in (self.strip, self.panel):
            win.realize()
            surface = win.get_surface()
            if surface is not None:
                xid = GdkX11.X11Surface.get_xid(surface)
                self.x11.set_hints(xid)
                self.x11.set_input(xid, False)
                self.x11.set_no_focus(xid)

        self.strip.set_visible(True)
        self.panel.set_visible(True)
        self.state = "fan"
        GLib.timeout_add(150, self.place_strip)
        GLib.timeout_add(150, self.place_panel)
        GLib.timeout_add(5300, self.end_demo)

    def end_demo(self):
        """Конец демо-показа: сворачиваем, даже если курсор оказался над панелью."""
        if self.state == "open":
            return False
        self.hide_source = 0
        self.state = "strip"
        self.panel.set_visible(False)
        return False

    def apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    # -- geometry --------------------------------------------------------

    def place(self, win, width, height, right_offset):
        surface = win.get_surface()
        if surface is None:
            return False
        xid = GdkX11.X11Surface.get_xid(surface)
        scale = surface.get_scale()
        self.scale = scale
        w = int(width * scale)
        h = int(height * scale)
        x = self.x11.root_w - int(right_offset * scale)
        self.x11.move_resize(xid, x, 0, w, h)
        self.x11.set_hints(xid)
        self.x11.set_input(xid, win is self.panel and self.state == "open")
        if not (win is self.panel and self.state == "open"):
            self.x11.set_no_focus(xid)
        win.xid = xid
        win.x_bounds = (x, x + w)
        print(
            f"[place] {win.get_title()}: x={x} w={w} h={h} scale={scale}",
            flush=True,
        )
        return False

    def place_strip(self):
        if not self.strip_h:
            self.strip_h = self.strip.get_height() or self.monitor_h
        return self.place(self.strip, STRIP_W, self.strip_h, STRIP_W)

    def place_panel(self):
        if not self.panel_h:
            self.panel_h = self.panel.get_height() or self.monitor_h
        return self.place(self.panel, PANEL_W, self.panel_h, PANEL_W + STRIP_W)

    # -- showing / hiding ------------------------------------------------

    def inside(self, x):
        for win in (self.strip, self.panel):
            bounds = getattr(win, "x_bounds", None)
            if bounds and win.get_visible() and bounds[0] <= x <= bounds[1]:
                return True
        return False

    def show_panel(self):
        self.show_source = 0
        if self.state == "open":
            return False
        if not self.panel.get_visible():
            self.panel.set_visible(True)
            GLib.timeout_add(30, self.place_panel)
        if self.state == "strip":
            self.state = "fan"
        return False

    def collapse_deck(self):
        if self.hide_source:
            GLib.source_remove(self.hide_source)
            self.hide_source = 0
        self.state = "strip"
        self.panel.set_visible(False)

    def schedule_hide(self):
        if self.state == "open":
            return
        if self.hide_source:
            GLib.source_remove(self.hide_source)
        self.hide_source = GLib.timeout_add(HIDE_CHECK_MS, self.maybe_hide)

    def maybe_hide(self):
        self.hide_source = 0
        if self.state == "open":
            return False
        point = self.x11.pointer()
        if point and self.inside(point[0]):
            return False
        self.state = "strip"
        self.panel.set_visible(False)
        return False

    def cancel_hide(self):
        if self.hide_source:
            GLib.source_remove(self.hide_source)
            self.hide_source = 0

    # -- widgets ---------------------------------------------------------

    def build_strip(self):
        self.strip = Gtk.Window(application=self)
        self.strip.set_title("Edge Notes — strip")
        self.strip.set_decorated(False)
        self.strip.set_resizable(False)
        self.strip.set_default_size(STRIP_W, self.monitor_h)
        box = Gtk.Box()
        box.add_css_class("strip")
        self.strip.set_child(box)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.show_panel())
        motion.connect("leave", lambda *_: self.schedule_hide())
        self.strip.add_controller(motion)

    def build_panel(self):
        self.panel = Gtk.Window(application=self)
        self.panel.set_title("Edge Notes — panel")
        self.panel.set_decorated(False)
        self.panel.set_resizable(False)
        self.panel.set_default_size(PANEL_W, self.monitor_h)
        self.panel.add_css_class("panel")

        self.stack = Gtk.Stack()
        self.stack.add_named(self.build_fan_page(), "fan")
        self.stack.add_named(self.build_note_page(), "note")
        self.stack.set_visible_child_name("fan")

        self.overlay = Gtk.Overlay()
        self.overlay.add_css_class("panel")
        self.overlay.set_child(self.stack)
        self.toast = Gtk.Revealer()
        self.toast.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.toast.set_halign(Gtk.Align.CENTER)
        self.toast.set_valign(Gtk.Align.END)
        self.toast.set_margin_bottom(12)
        toast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toast_box.add_css_class("toast")
        self.toast_label = Gtk.Label(label="Deleted.")
        undo = Gtk.Button(label="Undo")
        undo.connect("clicked", lambda *_: self.undo_delete())
        toast_box.append(self.toast_label)
        toast_box.append(undo)
        self.toast.set_child(toast_box)
        self.overlay.add_overlay(self.toast)
        self.panel.set_child(self.overlay)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.cancel_hide())
        motion.connect("leave", lambda *_: self.schedule_hide())
        self.panel.add_controller(motion)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.panel.add_controller(keys)

    def build_fan_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(page, f"set_margin_{side}")(10)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="NOTES")
        title.set_xalign(0)
        title.set_hexpand(True)
        title.add_css_class("header")
        add = Gtk.Button(label="+")
        add.set_tooltip_text("New note")
        add.connect("clicked", lambda *_: self.new_note())
        hide = Gtk.Button(label="×")
        hide.set_tooltip_text("Hide deck")
        hide.connect("clicked", lambda *_: self.collapse_deck())
        header.append(title)
        header.append(add)
        header.append(hide)
        page.append(header)

        hint = Gtk.Label(label="hover a note to peek · drag to reorder")
        hint.set_xalign(0)
        hint.add_css_class("hint")
        page.append(hint)

        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_child(self.rows)
        page.append(scroller)
        return page

    def build_note_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rail.add_css_class("rail")
        rail.set_size_request(112, -1)
        rail.set_vexpand(True)
        rail.set_margin_top(10)
        rail.set_margin_bottom(10)
        rail.set_margin_start(6)
        rail.set_margin_end(6)
        rail_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        close = Gtk.Button(label="×")
        close.set_tooltip_text("Close note (Esc)")
        close.connect("clicked", lambda *_: self.close_note())
        rail_top.append(close)
        rail.append(rail_top)

        self.rail_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rail_scroll = Gtk.ScrolledWindow()
        rail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rail_scroll.set_vexpand(True)
        rail_scroll.set_child(self.rail_rows)
        rail.append(rail_scroll)
        page.append(rail)

        self.text = Gtk.TextView()
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.set_left_margin(14)
        self.text.set_right_margin(14)
        self.text.set_top_margin(12)
        self.text.set_bottom_margin(12)
        self.text.add_css_class("editor")
        self.buffer = self.text.get_buffer()
        self.buffer.connect("changed", self.on_text_changed)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_vexpand(True)
        text_scroll.set_hexpand(True)
        text_scroll.set_child(self.text)
        page.append(text_scroll)
        return page

    def rebuild_fan(self):
        while (child := self.rows.get_first_child()):
            self.rows.remove(child)
        if not self.store.notes:
            empty = Gtk.Label(label="No notes yet — press +")
            empty.add_css_class("empty")
            self.rows.append(empty)
            return
        for note in self.store.notes:
            self.rows.append(self.make_row(note))

    def make_row(self, note):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        row.add_css_class("tab")
        title = Gtk.Label(label=first_line(note["text"]))
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("tab-title")
        preview = Gtk.Label(label=preview_text(note["text"]))
        preview.set_xalign(0)
        preview.set_wrap(True)
        preview.set_visible(False)
        preview.add_css_class("preview")
        row.append(title)
        row.append(preview)

        motion = Gtk.EventControllerMotion()
        self.attach_peek(row, preview)

        # One gesture for both: a press-and-release with no movement is a click,
        # anything further is a reorder. A separate GestureClick loses the race —
        # GestureDrag claims the sequence on press and cancels it.
        row.set_cursor(Gdk.Cursor.new_from_name("grab", None))
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda *_: self.drag_style(row, True))
        drag.connect("drag-end", lambda _g, dx, dy: self.finish_row(row, note["id"], dx, dy))
        drag.connect("cancel", lambda *_: self.drag_style(row, False))
        row.add_controller(drag)
        return row

    def drag_style(self, row, active):
        if active:
            row.add_css_class("tab-drag")
            row.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))
        else:
            row.remove_css_class("tab-drag")
            row.set_cursor(Gdk.Cursor.new_from_name("grab", None))

    def attach_peek(self, row, preview):
        state = {"source": 0}

        def show():
            state["source"] = 0
            preview.set_visible(True)
            return False

        def enter(*_):
            if state["source"]:
                GLib.source_remove(state["source"])
            state["source"] = GLib.timeout_add(PEEK_DELAY_MS, show)

        def leave(*_):
            if state["source"]:
                GLib.source_remove(state["source"])
                state["source"] = 0
            preview.set_visible(False)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", enter)
        motion.connect("leave", leave)
        row.add_controller(motion)

    def finish_row(self, row, note_id, dx, dy):
        self.drag_style(row, False)
        if abs(dx) < 5 and abs(dy) < 5:
            self.open_note(note_id)
        else:
            self.reorder(note_id, dy)

    def rebuild_rail(self):
        while (child := self.rail_rows.get_first_child()):
            self.rail_rows.remove(child)
        for note in self.store.notes:
            label = Gtk.Label(label=first_line(note["text"]))
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            button = Gtk.Button()
            button.add_css_class("railbtn")
            if note["id"] == self.current:
                button.add_css_class("railbtn-active")
            button.set_child(label)
            button.connect("clicked", lambda _b, nid=note["id"]: self.open_note(nid))
            self.rail_rows.append(button)

    # -- actions ---------------------------------------------------------

    def index_of(self, note_id):
        for i, note in enumerate(self.store.notes):
            if note["id"] == note_id:
                return i
        return -1

    def new_note(self):
        now = time.time()
        note = {"id": str(uuid.uuid4()), "text": "", "created": now, "updated": now}
        self.store.notes.insert(0, note)
        self.store.save()
        self.rebuild_fan()
        self.rebuild_rail()
        self.open_note(note["id"])

    def open_note(self, note_id):
        index = self.index_of(note_id)
        if index < 0:
            return
        self.flush_text()
        self.current = note_id
        self.state = "open"
        self.place_panel()
        self._loading = True
        self.buffer.set_text(self.store.notes[index]["text"])
        self.buffer.place_cursor(self.buffer.get_end_iter())
        self._loading = False
        self.stack.set_visible_child_name("note")
        self.rebuild_rail()
        xid = getattr(self.panel, "xid", None)
        if xid:
            self.x11.allow_focus(xid)
            self.panel.present()
        self.text.grab_focus()
        print(f"[open] {first_line(self.store.notes[index]['text'])}", flush=True)

    def close_note(self):
        self.flush_text()
        self.current = None
        self.state = "fan"
        xid = getattr(self.panel, "xid", None)
        if xid:
            self.x11.set_input(xid, False)
            self.x11.set_no_focus(xid)
        self.stack.set_visible_child_name("fan")
        self.rebuild_fan()
        self.rebuild_rail()
        print("[close]", flush=True)
        self.schedule_hide()

    def cycle(self, step):
        if not self.store.notes:
            return
        ids = [note["id"] for note in self.store.notes]
        index = ids.index(self.current) if self.current in ids else -1
        self.open_note(ids[(index + step) % len(ids)])

    def delete_current(self):
        if not self.current:
            return
        index = self.index_of(self.current)
        note = self.store.notes.pop(index)
        self.current = None
        self.state = "fan"
        self.stack.set_visible_child_name("fan")
        self.store.save()
        self.rebuild_fan()
        self.rebuild_rail()
        self.pending = (note, index)
        self.toast_label.set_text("Deleted. 10s to undo")
        self.toast.set_reveal_child(True)
        if self.undo_source:
            GLib.source_remove(self.undo_source)
        self.undo_source = GLib.timeout_add(UNDO_MS, self.expire_undo)

    def undo_delete(self):
        if not self.pending:
            return
        note, index = self.pending
        self.pending = None
        self.store.notes.insert(min(index, len(self.store.notes)), note)
        self.store.save()
        self.toast.set_reveal_child(False)
        self.rebuild_fan()
        self.rebuild_rail()
        self.open_note(note["id"])

    def expire_undo(self):
        self.undo_source = 0
        self.pending = None
        self.toast.set_reveal_child(False)
        return False

    def reorder(self, note_id, dy):
        delta = round(dy / ROW_H)
        if delta == 0:
            return
        index = self.index_of(note_id)
        target = max(0, min(len(self.store.notes) - 1, index + delta))
        if target == index:
            return
        note = self.store.notes.pop(index)
        self.store.notes.insert(target, note)
        self.store.save()
        self.rebuild_fan()
        self.rebuild_rail()
        print(f"[reorder] {first_line(note['text'])} -> {target}", flush=True)

    # -- editing ---------------------------------------------------------

    def on_text_changed(self, _buffer):
        if self._loading or not self.current:
            return
        if self.save_source:
            GLib.source_remove(self.save_source)
        self.save_source = GLib.timeout_add(SAVE_DEBOUNCE_MS, self.flush_text)

    def flush_text(self):
        self.save_source = 0
        if not self.current:
            return False
        index = self.index_of(self.current)
        if index < 0:
            return False
        text = self.buffer.get_text(
            self.buffer.get_start_iter(), self.buffer.get_end_iter(), False
        )
        note = self.store.notes[index]
        if note["text"] != text:
            note["text"] = text
            note["updated"] = time.time()
            self.store.save()
            self.rebuild_fan()
            self.rebuild_rail()
        return False

    # -- keys ------------------------------------------------------------

    def on_key(self, _controller, keyval, _keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if keyval == Gdk.KEY_Escape:
            if self.current:
                self.close_note()
            else:
                self.state = "strip"
                self.panel.set_visible(False)
            return True
        if ctrl and keyval == Gdk.KEY_q:
            self.quit()
            return True
        if ctrl and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.cycle(-1 if shift else 1)
            return True
        if ctrl and keyval == Gdk.KEY_BackSpace:
            self.delete_current()
            return True
        if ctrl and keyval == Gdk.KEY_z and self.pending:
            self.undo_delete()
            return True
        return False


if __name__ == "__main__":
    EdgeNotes().run([])
