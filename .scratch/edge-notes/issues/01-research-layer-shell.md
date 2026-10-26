# Layer-shell панель на GTK4 + PyGObject: работает ли на Ubuntu 24.04 / GNOME 46

Type: research
Status: resolved
Blocked by: —

## Question

Можно ли на этой машине (Ubuntu 24.04.5, Wayland, GNOME 46, GTK4 4.14, PyGObject 3.48) собрать приложение, которое:

- держит тонкую полоску у правого края экрана поверх обычных окон и не резервирует место в рабочей области;
- разворачивается в веер табов по наведению мыши (без клика и без фокуса клавиатуры);
- открывает панель заметки у того же края без декораций, с фокусом клавиатуры в `GtkTextView`;
- не появляется в доке и Alt+Tab и переживает переключение рабочих столов.

Ответить на конкретные вопросы:

1. Есть ли GIR/typelib для `GtkLayerShell` в `libgtk-layer-shell0` (или нужен dev-пакет) и вызывается ли он из Python: `gi.require_version('GtkLayerShell','0.1')`.
2. Минимальный код: `gtk_layer_init_for_window`, anchors, `set_exclusive_zone(0)`, `set_keyboard_mode`, `set_namespace`, margins. Что требуется от окна и от `GtkApplication`.
3. Работает ли hover на узкой полоске, когда окно не в фокусе; нужны ли `set_input_region` или трюки с `Gdk.Surface`.
4. Работает ли layer-shell под X11 и что именно ломается (fallback не нужен, но ограничение надо знать).
5. Как отлаживать: запуск из терминала, логи GTK, `WAYLAND_DEBUG`, looking glass.
6. Конфликты с окружением: Ubuntu Dock (слева), hot corner, обзор, полноэкранные приложения.
7. Ограничения GNOME 46: перетаскивание layer-shell окна, изменение размера, сворачивание, несколько мониторов, появление в доке/Alt+Tab.

Проверить на живой машине, где возможно. Установка `libgtk-layer-shell0`/`-dev` требует sudo с паролем — если без установки не проверить, описать точную команду для человека и всё, что можно узнать из пакетов и документации.

Источники: официальная документация gtk-layer-shell, репозиторий, документация GTK4, GNOME/Mutter. Ссылки на каждое утверждение.

## Answer

Layer-shell на этой машине не работает: GNOME/Mutter 46 не реализует `zwlr_layer_shell_v1` — его нет в живом реестре Wayland (27 globals), нет в `meta-wayland.c`, а upstream gtk4-layer-shell прямо пишет «does not work on … GNOME on Wayland». Пакет `libgtk-layer-shell0` в noble — GTK3-сборка: `gi.require_version('GtkLayerShell','0.1')` после Gtk 4.0 падает с `Requiring namespace 'Gtk' version '3.0', but '4.0' is already loaded`; typelib лежит отдельно в `gir1.2-gtklayershell-0.1`, а GTK4-версия (`Gtk4LayerShell 1.0`) в noble не упакована.

Hover без фокуса протоколом разрешён (pointer events не зависят от keyboard mode), но на GNOME это неприменимо: обычное GTK4-окно нельзя прижать к краю, сделать always-on-top или убрать из дока/Alt+Tab — API удалены, замены в xdg-shell нет.

Рабочие пути: (A) GNOME Shell extension — нативно, но UI на GJS/St; (B) XWayland + EWMH (`_NET_WM_STATE_ABOVE/SKIP_TASKBAR/STICKY`) — GTK4 сохраняется, хинты Mutter принимает (проверено), но это не Wayland; (C) сменить компоновщик на Sway/KDE. Детали, скетчи и источники: `.scratch/edge-notes/research/01-layer-shell.md`.
