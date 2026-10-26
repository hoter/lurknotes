# Глобальные горячие клавиши и единый экземпляр на GNOME 46

Type: research
Status: resolved
Blocked by: —

## Question

Как в v1 вызывать приложение глобально с клавиатуры на Ubuntu 24.04 / GNOME 46 / Wayland:

1. Поддерживает ли `xdg-desktop-portal-gnome` версии 46 портал `org.freedesktop.portal.GlobalShortcuts`? В какой версии GNOME он появился? Что отвечает `gdbus introspect` на этой машине.
2. Если портала нет — точная инструкция для человека: GNOME Settings → Keyboard → Custom Shortcuts, какая команда и аргументы (`edge-notes new`, `edge-notes all`), какие ограничения у такой привязки.
3. Как команда попадает в уже запущенный экземпляр: `GApplication` + D-Bus activation, `gapplication action`, собственный интерфейс. Что нужно, чтобы `edge-notes new` открывал панель и фокусировал редактор, а не запускал второе приложение.
4. Autostart: `~/.config/autostart/*.desktop`, поведение при логине в Wayland.
5. Ограничения Wayland: может ли приложение поднять окно и забрать фокус клавиатуры из фонового вызова; что с `xdg-activation` токенами.
6. Альтернативы, не требующие расширения GNOME Shell.

Проверить локально, что доступно (`gdbus`, `systemctl --user`, `dpkg -l 'xdg-desktop-portal*'`), остальное — по первичным источникам со ссылками.

## Answer

Портала `org.freedesktop.portal.GlobalShortcuts` на этой машине нет: бэкенд
`xdg-desktop-portal-gnome` 46.2 его не реализует, интерфейс отсутствует на шине
(`gdbus introspect`), в `gnome.portal` его нет, а в апстриме бэкенд появился только
в GNOME 48 (48.rc), причём 48 требует frontend ≥ 1.19.1 — здесь 1.18.4.

Схема v1: ручная привязка в GNOME Settings → Keyboard → Custom Shortcuts на
CLI-команду `~/.local/bin/edge-notes new` / `all` (свободные `Ctrl+Alt+N` и
`Ctrl+Alt+A`). Единый экземпляр — `Gtk.Application` + `application_id` +
`Gio.ApplicationFlags.HANDLES_COMMAND_LINE`: второй процесс отправляет argv в
primary по D-Bus и выходит. Фокус на Wayland не гарантирован: activation-token
надо взять из platform data и поставить окну через `set_startup_id()` до
`present()`; иначе Mutter лишь поднимет окно и пометит его urgent.

Автозапуск через `~/.config/autostart/edge-notes.desktop` (каталога ещё нет)
держит панель резидентной. Альтернатив без расширения Shell на GNOME 46 нет,
кроме системных evdev-демонов под root.

Полный разбор с источниками: [research/02-global-shortcut.md](../research/02-global-shortcut.md).
