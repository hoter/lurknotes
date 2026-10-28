# Research: X11/EWMH внутри strict-снапа

Type: research
Status: open
Blocked by:

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
