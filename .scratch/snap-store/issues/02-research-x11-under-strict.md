# Research: X11/EWMH внутри strict-снапа

Type: research
Status: resolved
Blocked by:

Research branch: `research/x11-under-strict` (findings: `.scratch/snap-store/research/02-x11-under-strict.md`)

## Question

Выживут ли текущие X11-трюки LurkNotes в strict-снапе под XWayland?

Проверить по первоисточникам (Snapcraft `x11` interface, snapd, XWayland,
Mutter/EWMH):

- доступен ли X11-дисплей из strict-снапа с `plugs: [x11]`, автосоединяется ли
  он и требует ли ручного `snap connect`;
- работают ли `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `STICKY`,
  `_NET_WM_DESKTOP`, `WM_HINTS.input`, `_NET_WM_USER_TIME`, `XMoveWindow` и
  позиционирование у края;
- доступны ли `libX11.so.6` и `ctypes`-вызовы из базы/extension или нужен
  `stage-packages: [libx11-6]`;
- есть ли особенности фокуса/кликов при `WM_HINTS.input = False` в снапе;
- что писать в листинге/манифесте про X11-зависимость.

Ответ — отчёт с ссылками и списком рисков; если strict не даёт поведения,
явно зафиксировать, что остаётся (classic/другой механизм).

## Answer

Resolved by research on branch `research/x11-under-strict`; full report:
<https://github.com/hoter/lurknotes/blob/research/x11-under-strict/.scratch/snap-store/research/02-x11-under-strict.md>

- A strict snap with `x11` **does see XWayland**: `DISPLAY=:0`, the Mutter
  `XAUTHORITY` cookie, and `XOpenDisplay` all work (verified inside a real strict
  snap). `x11` auto-connects on classic Ubuntu; no `snap connect` needed.
- `libX11.so.6` is not in core24 or gnome-46-2404, but GNOME snaps get it from
  `gpu-2404`/`mesa-2404` via the extension's `LD_LIBRARY_PATH`. A non-extension
  build would need `stage-packages: [libx11-6]` **and** the wrapper path.
- `ctypes` is available from core24's Python 3.12; PyGObject and
  `Gtk-4.0`/`GdkX11-4.0` typelibs come from `gnome-46-2404`.
- All EWMH tricks survive strict confinement and are retained by Mutter 46:
  `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `SKIP_PAGER`, `STICKY`,
  `_NET_WM_DESKTOP=0xFFFFFFFF`, `WM_HINTS.input=False`,
  `_NET_WM_USER_TIME=0`. `XMoveResizeWindow`/`XMoveWindow` are honoured; the
  window must stay undecorated (already done) or a 74 px frame appears.
- With `input=False`, clicks reach the window while `_NET_ACTIVE_WINDOW` does not
  move; Mutter may still set `_NET_WM_STATE_FOCUSED` after a click, so the app
  must keep reading `_NET_ACTIVE_WINDOW` (it does).
- `GDK_BACKEND=x11` is mandatory: `desktop-launch` forces Wayland when available.
  LurkNotes already sets it in `__main__.py`; do not remove it.
- Classic confinement is **not** needed for X11/EWMH and would not fix the real
  failure modes (missing XWayland, unconnected x11, lost GDK_BACKEND, missing
  libX11).
- Remaining for execution: a full LurkNotes snap build, GTK4/PyGObject e2e
  in-snap, autostart environment, fractional scaling. Listing text: "needs an
  X11 or XWayland session; no native Wayland mode".
