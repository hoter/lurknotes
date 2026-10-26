# Layer-shell панель на GTK4 + PyGObject: результаты исследования

**Машина:** Ubuntu 24.04.5, сессия Wayland, GNOME Shell 46.0, Mutter 46.2, GTK 4.14.5, PyGObject 3.48.2, libadwaita 1.5.0.
**Дата проверки:** 2026-10-26.
**Метод:** живая сессия + разбор пакетов без установки. `libgtk-layer-shell0`, `-dev`, `gir1.2-gtklayershell-0.1` и примеры были скачаны через `apt-get download` и распакованы в `/tmp/opencode/gll`; в систему ничего не устанавливалось (sudo с паролем). GIR/typelib проверялись через `GI_TYPELIB_PATH`/`LD_LIBRARY_PATH`.

---

## Краткий вердикт

**Layer-shell на этой машине не работает и не может работать.** GNOME/Mutter не реализует протокол `zwlr_layer_shell_v1`: в живом реестре Wayland его нет, в исходниках Mutter 46 нет его инициализации, а upstream-библиотеки прямо пишут, что GNOME-on-Wayland не поддерживается. Это не вопрос версии пакета или GTK.

Дополнительно: единственный пакет layer-shell в Ubuntu 24.04 (`libgtk-layer-shell0` 0.8.2) собран против **GTK 3**, а не GTK 4. GTK4-версия (`gtk4-layer-shell`, namespace `Gtk4LayerShell 1.0`) в noble вообще не упакована — её пришлось бы собирать из исходников, и даже после этого на GNOME она вернёт `is_supported() == False`.

Цель приложения (полоска у края, веер по hover, панель заметки, не в доке/Alt+Tab) **достижима, но другим механизмом**: GNOME Shell extension либо XWayland + EWMH. Оба варианта — компромисс; см. раздел «Что делать вместо layer-shell».

---

## Ответы

### 1. Есть ли GIR/typelib у `libgtk-layer-shell0` и как выглядит вызов из Python

**В `libgtk-layer-shell0` нет ни GIR, ни typelib.** Пакет содержит только разделяемую библиотеку:

```
libgtk-layer-shell0 0.8.2-1build2
  /usr/lib/x86_64-linux-gnu/libgtk-layer-shell.so.0.8.2
  NEEDED: libgtk-3.so.0, libgdk-3.so.0
```

GIR-описание лежит в `libgtk-layer-shell-dev`, скомпилированный typelib — в отдельном `gir1.2-gtklayershell-0.1`:

```
libgtk-layer-shell-dev
  /usr/share/gir-1.0/GtkLayerShell-0.1.gir
  pkgconfig: Requires.private: gtk+-3.0 >= 3.22.0

gir1.2-gtklayershell-0.1
  /usr/lib/x86_64-linux-gnu/girepository-1.0/GtkLayerShell-0.1.typelib
  Depends: gir1.2-gtk-3.0, libgtk-layer-shell0 (>= 0.6.0)
```

То есть `sudo apt install libgtk-layer-shell0` **недостаточно** для Python: нужен ещё `gir1.2-gtklayershell-0.1` (а для сборки — `libgtk-layer-shell-dev`).

**Главная проблема: это GTK3-сборка.** В GIR явно стоит `<include name="Gtk" version="3.0"/>`, а `.pc` требует `gtk+-3.0`. Проверка на живой машине с распакованными файлами:

```python
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GtkLayerShell as LS
print(LS.get_major_version(), LS.get_minor_version(), LS.get_micro_version())
print(LS.get_protocol_version(), LS.is_supported())
```

```
namespace ok, lib version: 0 8 2
protocol version: 0
is_supported: False
WARNING: It appears your Wayland compositor does not support the Layer Shell protocol
CRITICAL: layer_surface_new: assertion 'gtk_wayland_get_layer_shell_global ()' failed
WARNING: Falling back to XDG shell instead of Layer Shell
```

С GTK4 тот же импорт падает ещё до окна:

```python
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GtkLayerShell
```

```
gi.RepositoryError: Requiring namespace 'Gtk' version '3.0', but '4.0' is already loaded
ImportError: Requiring namespace 'Gtk' version '3.0', but '4.0' is already loaded
```

Причина: `GtkLayerShell-0.1.gir` включает `Gtk 3.0`; GObject Introspection не позволяет держать в одном процессе две версии namespace `Gtk`.

**Для GTK4 нужен другой проект и другой namespace:** upstream [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell), вызов:

```python
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk4LayerShell as LS
```

В Ubuntu 24.04 (noble) пакета с ним **нет** (`apt-cache search gtk4-layer-shell` пуст). Он появился только в более новых выпусках: plucky/questing — 1.0.4, resolute — 1.3.0 ([Launchpad](https://api.launchpad.net/1.0/ubuntu/+archive/primary?ws.op=getPublishedSources&source_name=gtk4-layer-shell&exact_match=true&status=Published), [Debian](https://sources.debian.org/src/gtk4-layer-shell/)). На noble его надо собирать из исходников; из нужных для сборки пакетов на машине нет `pkg-config`, `meson`, `ninja-build`, `libgtk-4-dev`, `libwayland-dev`, `wayland-protocols`, `gobject-introspection`, `libgirepository1.0-dev`.

Команды для человека (если он всё же хочет проверить GTK4-сборку):

```bash
sudo apt install pkg-config meson ninja-build libgtk-4-dev libwayland-dev \
  wayland-protocols gobject-introspection libgirepository1.0-dev

git clone https://github.com/wmww/gtk4-layer-shell.git
cd gtk4-layer-shell
meson setup build --prefix=/usr/local -Dexamples=true -Ddocs=false -Dtests=false
ninja -C build
sudo ninja -C build install
sudo ldconfig
```

Проверка после установки:

```bash
python3 - <<'EOF'
import ctypes
ctypes.CDLL("libgtk4-layer-shell.so.0")   # обязательно до libwayland-client
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk4LayerShell as L
print("supported:", L.is_supported(), "protocol:", L.get_protocol_version())
EOF
```

На GNOME 46 вывод будет `supported: False protocol: 0` — установка библиотеки ничего не меняет.

---

### 2. Минимальный код: anchors, exclusive_zone(0), keyboard_mode, namespace, margins

Ниже — API GTK4-версии (`gtk4-layer-shell`). Семантика та же, что у GTK3-версии; различия только в namespace и префиксе.

| Вызов | Что делает | Значения по умолчанию / нюансы |
|---|---|---|
| `init_for_window(win)` | Превращает `Gtk.Window` в layer surface | Обязательно **до** realize/`present()`; иначе окно уже стало xdg-toplevel |
| `set_namespace(win, "edge-notes-strip")` | Имя поверхности для правил/отладки компоновщика | По умолчанию `gtk4-layer-shell`; при смене на уже отображённом окне библиотека делает remap |
| `set_layer(win, Layer.TOP \| OVERLAY)` | Слой по z-порядку | По умолчанию `TOP`; `OVERLAY` выше обычных окон и, по протоколу, выше полноэкранных поверхностей |
| `set_anchor(win, Edge.RIGHT, True)` | Привязка к краю | Хотя бы один якорь; два противоположных (top+bottom) растягивают окно по этой оси |
| `set_margin(win, Edge.RIGHT, 0)` | Отступ от якоря | Работает только для привязанных краёв; при auto-exclusive-zone входит в зону |
| `set_exclusive_zone(win, 0)` | Сколько места резервировать в рабочей области | `0` — не резервировать; положительное — зарезервировать; `-1` — игнорировать чужие зоны и растянуться до краёв |
| `set_keyboard_mode(win, KeyboardMode.NONE)` | Нужен ли клавиатурный фокус | По умолчанию `NONE`; `ON_DEMAND` требует protocol v4; `EXCLUSIVE` забирает клавиатуру, пока поверхность сверху |
| `set_monitor(win, monitor)` | На какой выход положить поверхность | `NULL` — решает компоновщик; при смене на отображённом окне — remap |
| `set_default_size(w, h)` | Размер окна | Если окно растянуто противоположными якорями, размер по этой оси игнорируется; `0` — «по содержимому» |

Требования к окну и приложению:

- Окно — обычный `Gtk.Window`/`Gtk.ApplicationWindow` в GTK4-процессе; `Gtk.Application` нужен только как обычно (main loop, app id), специальных флагов layer-shell не требует.
- `init_for_window()` вызывать в `activate` до `present()`; для повторного показа использовать `set_hide_on_close(True)` и `present()`.
- Библиотека сама делает `set_decorated(False)`; дополнительно вызывать не обязательно.
- Работает только на Wayland-компоновщике с `zwlr_layer_shell_v1`. На GNOME `init_for_window()` печатает `WARNING: Failed to initialize layer surface, it appears your Wayland compositor doesn't support Layer Shell` и **возвращается**, а последующие `set_*` ругаются `GtkWindow is not a layer surface`; окно остаётся обычным xdg-toplevel.
- GTK3-версия на неподдерживаемом компоновщике не падает, а откатывается на XDG shell (это видно в warning выше).

**Панель заметки.** Для панели у того же края: `Layer.OVERLAY` (выше обычных окон и, по протоколу, выше полноэкранных), якоря `RIGHT/TOP/BOTTOM`, `exclusive_zone(0)`, `set_decorated(False)` (библиотека снимает декорации сама), `keyboard_mode = ON_DEMAND` (либо `EXCLUSIVE` только на время открытия), `Gtk.ScrolledWindow` + `Gtk.TextView`, после `present()` — `text_view.grab_focus()`. `ON_DEMAND` может потребовать клика по панели, чтобы компоновщик отдал клавиатуру; `EXCLUSIVE` гарантирует фокус, но блокирует клавиатуру для других приложений. На GNOME всё это неприменимо — там будет обычное окно.

Скелет — в разделе «Минимальный Python-скетч», вариант A.

---

### 3. Работает ли hover на узкой полоске без фокуса клавиатуры

**Да, на компоновщике с layer-shell — работает, и фокус клавиатуры для этого не нужен.** Это гарантирует сам протокол:

> «Layer surfaces receive pointer, touch, and tablet events normally. If you do not want to receive them, set the input region on your surface to an empty region.» — [wlr-layer-shell-unstable-v1.xml](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-layer-shell-unstable-v1.xml), описание `set_keyboard_interactivity`

То есть `keyboard_mode = NONE` отключает только клавиатуру; pointer enter/motion/leave приходят как обычно. На стороне GTK4 вешать `Gtk.EventControllerMotion` на окно/виджет; `is_active` окна не требуется.

Нюансы:

- **`set_input_region` не обязателен**, если вся полоска интерактивна. Он нужен только для click-through/фигурной области: у `gtk-layer-shell`/`gtk4-layer-shell` своего API для input region нет, в header прямо сказано «To control mouse/touch interactivity use input regions» ([gtk4-layer-shell.h](https://github.com/wmww/gtk4-layer-shell/blob/main/include/gtk4-layer-shell.h)). В GTK4 доступен `Gdk.Surface.set_input_region()` ([docs](https://docs.gtk.org/gdk4/method.Surface.set_input_region.html)); на этой машине `GdkWaylandDisplay.supports_input_shapes()` вернул `True` (проверено).
- **Скрытая поверхность не получает enter.** Полоска должна быть всё время замаплена; нельзя «показывать 1 px при уходе мыши» и ждать, что hover сработает. Держите видимую/невидимую, но замапленную полосу минимум 8–12 px по ширине — 1–2 px практически невозможно поймать мышью.
- **`can-target` vs input region.** `Gtk.Widget.set_can_target(False)` исключает виджет из GTK-пикинга, но не меняет Wayland input region всей поверхности. Для настоящего click-through нужен `Gdk.Surface.set_input_region()`.
- **Веер без ресайза.** Надёжнее держать окно фиксированного размера (например, 320 px в ширину на всю высоту), рисовать веер внутри, а input region выставлять только на видимую часть. Тогда hover-раскрытие не требует менять размер layer surface (смена размера — отдельный источник мерцания/гонок с configure).
- **Веер.** Его удобно делать `Gtk.Popover` от полоски: gtk4-layer-shell поддерживает GTK popups/popovers. Но у popover своё поведение autohide/grab, и hover-раскрытие всё равно придётся настраивать вручную.
- **GNOME 46:** layer surface нет; hover на обычном окне работает, но окно нельзя прижать к краю и поднять над другими. Для сценария «полоска у правого края» это не помогает.

Отдельно про клавиатуру в панели заметки: `ON_DEMAND` даёт фокус по клику, но не гарантирует его при программном `present()`; `EXCLUSIVE` гарантирует фокус, пока панель в верхнем слое, но забирает клавиатуру у других приложений. Для редактора заметки обычно нужен `ON_DEMAND` + явный клик (либо временный `EXCLUSIVE`, пока панель открыта). Проверить это можно только на поддерживающем компоновщике.

---

### 4. Работает ли layer-shell под X11 и что ломается

**Нет.** Библиотека работает только на Wayland:

- `gtk_layer_is_supported()` возвращает `TRUE` только если платформа — Wayland и компоновщик объявил `zwlr_layer_shell_v1` ([header](https://github.com/wmww/gtk4-layer-shell/blob/main/include/gtk4-layer-shell.h)).
- На X11 `init_for_window()` печатает `WARNING: Failed to initialize layer surface, not on Wayland` и возвращается ([исходник](https://github.com/wmww/gtk4-layer-shell/blob/main/src/gtk4-layer-shell.c)); у GTK3-версии аналогично, с откатом на XDG shell на неподдерживаемом Wayland.
- В README обоих проектов: «This library only works on Wayland… It does not work on X11 or GNOME on Wayland» ([gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell), [gtk-layer-shell](https://github.com/wmww/gtk-layer-shell)).

`GDK_BACKEND=x11` в Wayland-сессии — это XWayland, то есть приложение становится X11-клиентом. Layer-shell там нет, но EWMH-хинты позволяют приблизиться к нужному поведению (см. вариант B).

---

### 5. Как отлаживать

1. **Ранняя проверка поддержки** в коде:
   ```python
   print("supported:", LS.is_supported(), "protocol:", LS.get_protocol_version())
   ```
   `0`/`False` — дальше идти бессмысленно. Функция может сделать Wayland-roundtrip при первом вызове.

2. **`WAYLAND_DEBUG=1`** — клиентский лог libwayland. Запустить минимальное GTK4-окно и посмотреть, какие globals объявляет компоновщик:
   ```bash
   WAYLAND_DEBUG=1 python3 wlprobe.py 2>wl.log
   grep -oE 'wl_registry@2\.global\([0-9]+, "[^"]+"' wl.log | sed -E 's/.*"([^"]+)"/\1/' | sort -u
   ```
   На этой машине в списке 27 globals, и `zwlr_layer_shell_v1` среди них нет (полный список — ниже). Это самый быстрый способ отличить «библиотека не установлена» от «компоновщик не умеет».

3. **`G_MESSAGES_DEBUG=all`** — включает предупреждения GTK/GLib; warning-и `gtk4-layer-shell` про «compositor doesn't support Layer Shell» видно и без него, но с ним больше контекста.

4. **`gtk4-layer-demo`** — демо из upstream `gtk4-layer-shell`, показывает все фичи и текущую поддержку компоновщика. В Ubuntu есть `gtk-layer-demo` (GTK3) в пакете `gtk-layer-shell-examples`; на GNOME он тоже покажет «not supported».

5. **GTK Inspector:** `GTK_DEBUG=interactive` (или `Ctrl+Shift+D` при включённых keybinding-ах) — проверить, что окно действительно стало layer surface, какие у него размеры/якоря.

6. **GNOME-сторона (для extension-варианта):**
   ```bash
   journalctl -f -o cat /usr/bin/gnome-shell
   ```
   Looking Glass: `Alt+F2`, команда `lg`. `org.gnome.Shell.Eval` по D-Bus в этой сессии **заблокирован**: вызов вернул `(false, '')`, так что использовать его для интроспекции окон нельзя. Для extension-разработки — `gnome-extensions` CLI и gjs.guide.

7. **XWayland-вариант:** `xprop -id <xid> _NET_WM_STATE _NET_WM_DESKTOP`, `xwininfo -root -tree`, `xprop -root _NET_CLIENT_LIST_STACKING`. Этого достаточно, чтобы увидеть, принял ли Mutter `_NET_WM_STATE_ABOVE`/`SKIP_TASKBAR`/`STICKY`.

Полный список globals с этой машины (27, без layer-shell):

```
gtk_shell1, wl_compositor, wl_data_device_manager, wl_output, wl_seat,
wl_shm, wl_subcompositor, wp_fractional_scale_manager_v1, wp_presentation,
wp_single_pixel_buffer_manager_v1, wp_viewporter, xdg_activation_v1,
xdg_wm_base, zwp_idle_inhibit_manager_v1,
zwp_keyboard_shortcuts_inhibit_manager_v1, zwp_linux_dmabuf_v1,
zwp_pointer_constraints_v1, zwp_pointer_gestures_v1,
zwp_primary_selection_device_manager_v1, zwp_relative_pointer_manager_v1,
zwp_tablet_manager_v2, zwp_text_input_manager_v3, zxdg_exporter_v1,
zxdg_exporter_v2, zxdg_importer_v1, zxdg_importer_v2,
zxdg_output_manager_v1
```

---

### 6. Конфликты с окружением: Ubuntu Dock, hot corner, обзор, полноэкранные приложения

На GNOME 46 layer-shell нет, поэтому «конфликтов layer-shell с GNOME-окружением» тоже нет — есть конфликты **обычного окна** с окружением. На компоновщике с layer-shell картина другая:

- **Ubuntu Dock (слева)** — это GNOME Shell extension `ubuntu-dock@ubuntu.com` (пакет `gnome-shell-extension-ubuntu-dock 90ubuntu3`, локально `/usr/share/gnome-shell/extensions/ubuntu-dock@ubuntu.com/`), живёт в shell chrome, а не в layer-shell. На GNOME полоска-окно получит иконку в доке; на Sway/KDE дока в таком виде нет. Правая полоска с левым доком геометрически не конфликтует.
- **Hot corner** (левый верхний угол) — правая полоска его не задевает. Если делать прозрачный overlay на весь экран, input region не должен покрывать угол, иначе hot corner перестанет срабатывать.
- **Обзор (Overview)** — layer surfaces обычно не представлены в обзоре как окна; могут оставаться поверх или скрываться — поведение зависит от компоновщика. Обычные окна и XWayland-окна попадают в обзор как thumbnails.
- **Полноэкранные приложения** — по протоколу слои идут `background < bottom < top < overlay`, а полноэкранные shell-поверхности «typically rendered at the top layer». Значит, `OVERLAY` остаётся выше полноэкранного окна, `TOP` может оказаться ниже. На GNOME обычное окно полноэкранное приложение не перекрывает.
- **Exclusive zone** — `0` не резервирует рабочую область, но компоновщик может сдвинуть поверхность, чтобы она не перекрывала чужие positive-зоны (например, верхнюю панель). `-1` игнорирует чужие зоны, но растягивает поверхность до якорей.
- **Screen lock / session lock** — отдельный протокол; layer surfaces на время блокировки скрываются компоновщиком. Не рассчитывайте, что панель будет видна на lock screen.

---

### 7. Ограничения GNOME 46: перетаскивание, размер, сворачивание, мониторы, док/Alt+Tab

**Layer-shell на GNOME 46 отсутствует.** Это подтверждается тремя независимыми способами:

1. **Живой реестр Wayland:** 27 globals, `zwlr_layer_shell_v1` нет (см. Q5).
2. **Исходники Mutter 46:** в `meta_wayland_compositor_new()` инициализируются compositor, shm, outputs, data device, subsurfaces, shell, tablet, seat, xdg-foreign, dma-buf, single-pixel-buffer, keyboard-shortcuts-inhibit, text-input, presentation-time, activation, transaction, idle-inhibit, drm-syncobj — **ни layer-shell, ни файлов с его реализацией в `src/wayland/` нет** ([meta-wayland.c](https://github.com/GNOME/mutter/blob/gnome-46/src/wayland/meta-wayland.c)).
3. **Upstream:** «Layer shell is not supported on: Gnome-on-Wayland» ([gtk-layer-shell README](https://github.com/wmww/gtk-layer-shell)); «It does not work on X11 or GNOME on Wayland» ([gtk4-layer-shell.h](https://github.com/wmww/gtk4-layer-shell/blob/main/include/gtk4-layer-shell.h)); в таблице поддержки протокола у Mutter стоит «x» ([wayland.app](https://wayland.app/protocols/wlr-layer-shell-unstable-v1)).

Что это значит для требований:

- **Прижать к краю / always-on-top / не резервировать место** — нельзя. В GTK4 удалены `gtk_window_move()`, `gtk_window_set_keep_above()`, `gtk_window_set_keep_below()`, `gtk_window_set_position()`; X11-специфичные `skip-taskbar`, `sticky`, `keep-below`, `window groups` тоже удалены или вынесены в X11-backend ([GTK4 migration guide](https://docs.gtk.org/gtk4/migrating-3to4.html)). В xdg-shell замены нет.
- **`set_decorated(False)`** работает ([docs](https://docs.gtk.org/gtk4/method.Window.set_decorated.html)), но окно остаётся обычным toplevel: GNOME сам выбирает позицию, окно попадает в док/Alt+Tab/обзор, живёт на одной рабочей области, уходит под полноэкранные приложения.
- **Перетаскивание/размер/сворачивание:** обычное окно — силами WM (пользователь тащит за заголовок/края, сворачивает). Layer surface — не управляется WM: перетаскивания и resize-ручек нет, сворачивания нет (только hide/unmap); двигать/менять размер нужно самому, меняя margins/anchors/размер.
- **Несколько мониторов:** у layer-shell — `set_monitor()`; `NULL` означает «решает компоновщик» (обычно тот выход, где последнее взаимодействие). При hotplug библиотека делает remap; начиная с gtk4-layer-shell 1.3 событие `closed` по умолчанию не destroys окно (см. `set_respect_close`). У обычного окна на GNOME API размещения нет; позицию выбирает GNOME.
- **Док/Alt+Tab:** layer surface не является toplevel, поэтому в доке/Alt+Tab не появляется (на компоновщиках, где он есть). На GNOME окно обычное и появляется; убрать его из Alt+Tab на Wayland нельзя. Единственный путь — XWayland + `_NET_WM_STATE_SKIP_TASKBAR` (см. ниже): Mutter его принимает, а GNOME Shell 46 фильтрует такие окна в Alt+Tab (`!w.skip_taskbar` в [altTab.js](https://github.com/GNOME/gnome-shell/blob/gnome-46/js/ui/altTab.js)).

---

## Минимальный Python-скетч

### Вариант A: layer-shell (эталон; на GNOME 46 не запустится)

Требуется собранный/установленный `gtk4-layer-shell` (namespace `Gtk4LayerShell 1.0`). На Ubuntu 24.04 его нет; на GNOME `is_supported()` вернёт `False` и скрипт завершится.

```python
#!/usr/bin/env python3
# Только для компоновщиков с zwlr_layer_shell_v1 (Sway, KDE, wlroots, Mir...).
import ctypes
ctypes.CDLL("libgtk4-layer-shell.so.0")   # обязательно до libwayland-client

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gtk4LayerShell as LS


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.example.EdgeNotes")
        self.panel = None
        self.text_view = None

    def do_activate(self):
        if not LS.is_supported():
            print("layer-shell unsupported, protocol =", LS.get_protocol_version())
            self.quit()
            return
        self.strip = self._make_strip()
        self.strip.present()

    def _make_strip(self):
        w = Gtk.Window(application=self)
        w.set_default_size(12, 600)          # ширина полоски; высоту растянем якорями
        LS.init_for_window(w)                # до realize/present!
        LS.set_namespace(w, "edge-notes-strip")
        LS.set_layer(w, LS.Layer.OVERLAY)    # выше обычных окон и полноэкранных
        for edge in (LS.Edge.RIGHT, LS.Edge.TOP, LS.Edge.BOTTOM):
            LS.set_anchor(w, edge, True)     # правый край, на всю высоту
        LS.set_margin(w, LS.Edge.RIGHT, 0)
        LS.set_exclusive_zone(w, 0)          # место в рабочей области не резервируем
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)  # клавиатура не нужна

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._open_panel())
        w.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: print("hover enter"))  # здесь раскрывать веер
        motion.connect("leave", lambda *_: print("hover leave"))
        w.add_controller(motion)

        w.set_child(Gtk.Label(label="⋮"))
        return w

    def _open_panel(self):
        if self.panel is None:
            w = Gtk.Window(application=self)
            w.set_default_size(420, 600)
            w.set_decorated(False)
            w.set_hide_on_close(True)
            LS.init_for_window(w)
            LS.set_namespace(w, "edge-notes-panel")
            LS.set_layer(w, LS.Layer.OVERLAY)
            for edge in (LS.Edge.RIGHT, LS.Edge.TOP, LS.Edge.BOTTOM):
                LS.set_anchor(w, edge, True)
            LS.set_exclusive_zone(w, 0)
            # ON_DEMAND: фокус по клику. EXCLUSIVE заберёт клавиатуру у других окон.
            LS.set_keyboard_mode(w, LS.KeyboardMode.ON_DEMAND)

            self.text_view = Gtk.TextView()
            self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_child(self.text_view)
            w.set_child(scrolled)
            self.panel = w

        self.panel.present()
        self.text_view.grab_focus()  # может потребовать клика по панели при ON_DEMAND


App().run(None)
```

Замечания к скетчу:

- `set_default_size(12, 600)` при якорях top+bottom: высота будет растянута, ширина останется 12. Для веера лучше фиксированное окно шириной ~320 px с прозрачным фоном и input region только на видимой части.
- `set_exclusive_zone(0)` — не резервировать место. Не вызывайте `auto_exclusive_zone_enable()`, иначе рабочая область уменьшится.
- `keyboard_mode` можно менять на лету: полоска `NONE`, панель `ON_DEMAND`/`EXCLUSIVE`.
- Панель заметки: `OVERLAY` + якоря right/top/bottom + `set_decorated(False)` + `GtkTextView`; библиотека сама снимает декорации.
- На GNOME этот скрипт дойдёт до `is_supported() == False` и выйдет.

### Вариант B: XWayland + EWMH (то, что реально запускается на этой машине)

Это **не layer-shell**, а X11-окно под XWayland. Проверено: Mutter 46 принимает `_NET_WM_STATE_ABOVE`, `_NET_WM_STATE_SKIP_TASKBAR`, `_NET_WM_STATE_STICKY` и `_NET_WM_DESKTOP = 0xFFFFFFFF`; GNOME Shell 46 фильтрует `skip_taskbar` в Alt+Tab, Ubuntu Dock — в списке окон. Позиционирование — X11-координатами. Ниже — компактный прототип; он не заменяет layer-shell, но сохраняет GTK4/PyGObject и `GtkTextView`.

```python
import os
os.environ["GDK_BACKEND"] = "x11"          # до импорта Gtk!

import ctypes
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkX11", "4.0")
from gi.repository import Gdk, GdkX11, Gtk, GLib

X = ctypes.CDLL("libX11.so.6")
X.XOpenDisplay.restype = ctypes.c_void_p
X.XOpenDisplay.argtypes = [ctypes.c_char_p]
X.XDefaultRootWindow.restype = ctypes.c_ulong
X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
X.XInternAtom.restype = ctypes.c_ulong
X.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
X.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                         ctypes.c_long, ctypes.c_void_p]
X.XMoveResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
X.XFlush.argtypes = [ctypes.c_void_p]


class _Msg(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _Ev(ctypes.Union):
    _fields_ = [("c", _Msg), ("pad", ctypes.c_long * 24)]


dpy = X.XOpenDisplay(None)
root = X.XDefaultRootWindow(dpy)
atom = lambda n: X.XInternAtom(dpy, n.encode(), 0)


def send(xid, message_type, d0, d1=0):
    ev = _Ev()
    ev.c.type = 33            # ClientMessage
    ev.c.send_event = 1
    ev.c.display = dpy
    ev.c.window = xid
    ev.c.message_type = message_type
    ev.c.format = 32
    ev.c.data[0], ev.c.data[1] = d0, d1
    X.XSendEvent(dpy, root, 0, (1 << 20) | (1 << 19), ctypes.byref(ev))
    X.XFlush(dpy)


def make_edge_window(app, width=360):
    # вызывать из Gtk.Application.do_activate: make_edge_window(self)
    w = Gtk.Window(application=app)
    w.set_decorated(False)
    w.set_default_size(width, 600)
    w.present()

    def after_map():
        xid = GdkX11.X11Surface.get_xid(w.get_surface())
        mon = Gdk.Display.get_default().get_monitors().get_item(0)
        g = mon.get_geometry()
        X.XMoveResizeWindow(dpy, xid, g.x + g.width - width, g.y, width, g.height)

        state = atom("_NET_WM_STATE")
        send(xid, state, 1, atom("_NET_WM_STATE_ABOVE"))
        send(xid, state, 1, atom("_NET_WM_STATE_SKIP_TASKBAR"))
        send(xid, state, 1, atom("_NET_WM_STATE_STICKY"))
        send(xid, atom("_NET_WM_DESKTOP"), 0xFFFFFFFF)  # все рабочие области
        return False

    GLib.timeout_add(200, after_map)
    return w
```

Проверка после запуска:

```bash
xprop -id <xid> _NET_WM_STATE _NET_WM_DESKTOP
# ожидаемо: _NET_WM_STATE_ABOVE, _NET_WM_STATE_SKIP_TASKBAR,
#           _NET_WM_STATE_STICKY, _NET_WM_STATE_FOCUSED;
#           _NET_WM_DESKTOP = 4294967295
```

Что в этом варианте **не** проверено глазами: действительно ли окно выше Wayland-окон и полноэкранных приложений, и не остаётся ли иконка в доке, если приложение закреплено. Хинты Mutter принимает — это проверено; визуальный z-order и док-поведение требуют ручного теста. Позиционирование через `XMoveResizeWindow` в прототипе тоже не проверялось визуально — проверьте на своём мониторе.

---

## Что делать вместо layer-shell на GNOME 46

| Путь | Что получаем | Чем платим | Когда выбирать |
|---|---|---|---|
| **A. GNOME Shell extension** | Нативный chrome-актор: выше окон, на всех рабочих областях, не в доке/Alt+Tab, можно дать клавиатурный фокус. Установка без sudo, в `~/.local/share/gnome-shell/extensions`. | UI пишется на GJS/St, а не GTK4; вместо `GtkTextView` — `St.Entry`/`Clutter.Text` (или отдельное GTK-окно); код живёт в процессе gnome-shell (падение расширения может уронить сессию); API расширений меняется между версиями; на Wayland после правок нужен перелогин/вложенная сессия. | Если нужен «нативный» вид и поведение без XWayland. |
| **B. XWayland + EWMH** | Сохраняем GTK4/PyGObject, `GtkTextView`, обычные виджеты; окно можно поставить к краю, поднять (`ABOVE`), убрать из Alt+Tab/дока (`SKIP_TASKBAR`), сделать sticky. | Приложение — X11-клиент под XWayland, не чистый Wayland; окно может один раз забрать фокус при map; выше полноэкранного — не гарантировано; fractional scaling/качество шрифтов хуже; в обзоре окно, скорее всего, останется. | Если важнее сохранить текущий GTK4-код и быстро получить рабочий прототип. |
| **C. Сменить компоновщик** | Layer-shell работает как задумано: якоря, exclusive zone, hover без фокуса, overlay выше fullscreen. | Другой десктоп (Sway/KDE/…), перенос настроек, потеря GNOME-специфики. | Если layer-shell — жёсткое требование, а не GNOME. |
| **D. Обычное окно** | Просто, нативно, без хаков. | Нет края/always-on-top/скрытия из дока/Alt+Tab; позицию выбирает GNOME. | Если требования можно ослабить. |

Практичная гибридная схема: **extension для полоски/веера** (он не окно, поэтому док/Alt+Tab/рабочие области решаются сами) + **обычное GTK4-окно для редактора заметки** (клавиатура и `GtkTextView` работают нативно; но окно не будет у края и появится в Alt+Tab). Либо **XWayland для всего**, если критично «всё в одном GTK4-приложении».

---

## Ограничения и риски

1. **Платформенный блокер.** GNOME/Mutter 46 не реализует `zwlr_layer_shell_v1`. Ни установка пакета, ни сборка gtk4-layer-shell это не исправит. Любой дизайн, завязанный на layer-shell, на этой машине не запустится.
2. **Пакетный блокер для GTK4.** В noble `libgtk-layer-shell0` — GTK3-сборка; `gi.require_version('GtkLayerShell','0.1')` несовместим с уже загруженным GTK4; GTK4-версия не упакована и требует сборки из исходников (плюс `pkg-config`/`meson`/`ninja`/`libgtk-4-dev`, которых нет).
3. **Клавиатурный фокус на layer surface.** `ON_DEMAND` не гарантирует фокус при программном открытии панели; `EXCLUSIVE` гарантирует, но забирает клавиатуру глобально. Для `GtkTextView` это ключевой UX-риск: возможно, потребуется клик по панели или временный `EXCLUSIVE`.
4. **Hover на тонкой полоске.** Нужна замапленная поверхность и достаточная площадь попадания (8–12 px). Скрытая/1-px поверхность не получит enter. Ресайз layer surface на hover — источник мерцания; лучше фиксированный прозрачный overlay + input region.
5. **Нет WM-управления layer surface.** Нельзя перетащить/изменить размер/свернуть стандартными средствами; всё делать вручную через margins/anchors/размер. `gtk_window_begin_move_drag()` в GTK4 удалён; `Gdk.Toplevel.begin_move()` рассчитан на xdg-toplevel и требует события ввода.
6. **Полноэкранный режим.** `OVERLAY` по протоколу выше `TOP` и обычно выше fullscreen; `TOP` может быть ниже. Поведение всё равно «implementation-dependent» — проверять на целевом компоновщике.
7. **Несколько мониторов.** `set_monitor(NULL)` оставляет выбор компоновщику; при hotplug — remap/`closed`. Нужно решать, что делать при исчезновении монитора (переехать на другой/скрыть), и не терять окно.
8. **Док/Alt+Tab на GNOME.** Обычное окно появляется везде; на Wayland убрать нельзя. XWayland+`SKIP_TASKBAR` помогает (Mutter принимает, Shell/Dock фильтруют), но закреплённая иконка в доке может остаться; обзор, скорее всего, покажет окно.
9. **XWayland-компромиссы.** Не чистый Wayland; возможен разовый захват фокуса при map; фракционное масштабирование и качество рендера хуже; above-fullscreen не гарантирован; при обновлении GNOME поведение EWMH может измениться.
10. **Shell extension-риски.** Код исполняется в gnome-shell; ошибка может замедлить/уронить сессию. Нет GTK-виджетов; `GtkTextView` не переиспользовать. API расширений привязан к версии Shell (46), при обновлении GNOME возможны поломки.
11. **Безопасность/блокировка экрана.** Layer surfaces скрываются lock screen; не храните в панели секреты, не рассчитывайте на видимость при блокировке.
12. **Тестовые пробелы.** На этой машине нельзя проверить сам layer-shell (его нет). Визуально не проверены: z-order XWayland `ABOVE` над Wayland/fullscreen, поведение дока при `SKIP_TASKBAR`, sticky на динамических рабочих областях, фокус `ON_DEMAND` на wlroots/KDE. Для всего этого нужен либо другой компоновщик, либо ручной тест человеком.

### Что осталось непроверенным и как это проверить человеку

- **Убедиться, что layer-shell на GNOME не появится:** уже проверено тремя способами; повторять не нужно. Для наглядности:
  ```bash
  sudo apt install libgtk-layer-shell0 gir1.2-gtklayershell-0.1 gtk-layer-shell-examples
  gtk-layer-demo   # GTK3-демо; на GNOME покажет, что протокол не поддерживается
  ```
- **Собрать GTK4-версию и проверить `is_supported()`** — команды в Q1. Ожидаемо `False` на GNOME.
- **Проверить XWayland-фолбэк глазами:** запустить прототип из варианта B, открыть обычное окно и fullscreen-приложение, проверить: полоска сверху, не в Alt+Tab, не в доке (если не закреплена), остаётся при переключении рабочих областей, `xprop` показывает нужные атомы.
- **Проверить extension-путь:** `gnome-extensions create --interactive`, `Main.layoutManager.addChrome(actor, {trackFullscreen: false})`, `global.stage.set_key_focus(actor)`; тестировать во вложенной сессии или после перелогина (Wayland не перезапускает shell).
- **Проверить `ON_DEMAND` vs `EXCLUSIVE`** для панели заметки на Sway/KDE — только там layer-shell вообще есть.

---

## Источники

### Первичные (пакеты, протокол, исходники)

- **Пакеты Ubuntu 24.04:**
  - [`libgtk-layer-shell0`](https://packages.ubuntu.com/noble/libgtk-layer-shell0) — 0.8.2-1build2, зависит от `libgtk-3-0t64`; состав пакета проверен `dpkg-deb -c`.
  - [`libgtk-layer-shell-dev`](https://packages.ubuntu.com/noble/libgtk-layer-shell-dev) — содержит `GtkLayerShell-0.1.gir`, `.pc` с `gtk+-3.0`.
  - [`gir1.2-gtklayershell-0.1`](https://packages.ubuntu.com/noble/gir1.2-gtklayershell-0.1) — typelib, зависит от `gir1.2-gtk-3.0`.
  - [`gtk-layer-shell-examples`](https://packages.ubuntu.com/noble/gtk-layer-shell-examples) — `gtk-layer-demo` (GTK3).
- **Протокол layer-shell:** [wlr-layer-shell-unstable-v1.xml](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-layer-shell-unstable-v1.xml) — pointer events, exclusive zone, keyboard modes, слои; [Wayland Explorer](https://wayland.app/protocols/wlr-layer-shell-unstable-v1) — таблица поддержки компоновщиков (Mutter — «x»).
- **GTK4-библиотека:** [wmww/gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell) — README, [`include/gtk4-layer-shell.h`](https://github.com/wmww/gtk4-layer-shell/blob/main/include/gtk4-layer-shell.h) (цитата про X11/GNOME), [`src/gtk4-layer-shell.c`](https://github.com/wmww/gtk4-layer-shell/blob/main/src/gtk4-layer-shell.c) (warning при отсутствии протокола), [`examples/simple-example.py`](https://github.com/wmww/gtk4-layer-shell/blob/main/examples/simple-example.py) (preload через ctypes, namespace `Gtk4LayerShell 1.0`).
- **GTK3-библиотека:** [wmww/gtk-layer-shell](https://github.com/wmww/gtk-layer-shell) — README: GTK3, maintenance mode, GNOME не поддерживается; заголовок [`gtk-layer-shell.h`](https://github.com/wmww/gtk-layer-shell/blob/master/include/gtk-layer-shell.h).
- **Mutter 46:** [`src/wayland/meta-wayland.c`](https://github.com/GNOME/mutter/blob/gnome-46/src/wayland/meta-wayland.c) — список инициализируемых протоколов без layer-shell; [`src/x11/window-x11.c`](https://github.com/GNOME/mutter/blob/gnome-46/src/x11/window-x11.c) — обработка `_NET_WM_STATE_SKIP_TASKBAR` и `_NET_WM_STATE_ABOVE`.
- **GNOME Shell 46:** [`js/ui/layout.js`](https://github.com/GNOME/gnome-shell/blob/gnome-46/js/ui/layout.js) — `addChrome`/`addTopChrome`, `affectsInputRegion`, `trackFullscreen`; [`js/ui/altTab.js`](https://github.com/GNOME/gnome-shell/blob/gnome-46/js/ui/altTab.js) — фильтр `!w.skip_taskbar`.
- **Ubuntu Dock:** локальный `/usr/share/gnome-shell/extensions/ubuntu-dock@ubuntu.com/appIcons.js` (пакет `gnome-shell-extension-ubuntu-dock 90ubuntu3`) — `getInterestingWindows()` фильтрует `!w.skipTaskbar`.
- **GTK4 API:** [Migrating from GTK 3 to GTK 4](https://docs.gtk.org/gtk4/migrating-3to4.html) — удаление `gtk_window_move`, `set_keep_above`, `skip-taskbar`/`sticky` как X11-only; [`Gtk.Window.set_decorated`](https://docs.gtk.org/gtk4/method.Window.set_decorated.html); [`Gdk.Surface.set_input_region`](https://docs.gtk.org/gdk4/method.Surface.set_input_region.html).
- **Упаковка gtk4-layer-shell в новых Ubuntu:** [Launchpad API](https://api.launchpad.net/1.0/ubuntu/+archive/primary?ws.op=getPublishedSources&source_name=gtk4-layer-shell&exact_match=true&status=Published) — plucky/questing 1.0.4, resolute 1.3.0; [Debian sources](https://sources.debian.org/src/gtk4-layer-shell/) — trixie/sid.
- **Отладка:** [GTK4 running/debug](https://docs.gtk.org/gtk4/running.html), [GLib running](https://docs.gtk.org/glib/running.html), [gjs.guide: creating an extension](https://gjs.guide/extensions/development/creating.html), [gjs.guide: debugging](https://gjs.guide/extensions/development/debugging.html).

### Локальные проверки (воспроизводимы)

- `apt-cache policy/show libgtk-layer-shell0 libgtk-layer-shell-dev gir1.2-gtklayershell-0.1 gtk-layer-shell-examples`
- `dpkg-deb -c` и `objdump -p` для скачанных `.deb` — состав и `NEEDED`.
- `GI_TYPELIB_PATH=… LD_LIBRARY_PATH=… python3 gi3_probe.py` — GTK3-импорт, `is_supported() == False`, warning «compositor does not support Layer Shell».
- `GI_TYPELIB_PATH=… python3 gi_test.py` — GTK4-импорт `GtkLayerShell 0.1` падает с `Requiring namespace 'Gtk' version '3.0', but '4.0' is already loaded`.
- `WAYLAND_DEBUG=1 python3 wlprobe.py` — 27 globals, `zwlr_layer_shell_v1` отсутствует.
- `python3 ewmh_probe.py` — `_NET_WM_STATE` c `ABOVE`, `SKIP_TASKBAR`, `STICKY`, `_NET_WM_DESKTOP=0xFFFFFFFF`; `xprop` подтверждает.
- `gdbus call … org.gnome.Shell.Eval 'global.get_window_actors().length'` → `(false, '')` (Eval заблокирован).
- `gnome-shell --version` → 46.0; `libmutter-14-0` → 46.2; GTK 4.14.5; PyGObject 3.48.2.
