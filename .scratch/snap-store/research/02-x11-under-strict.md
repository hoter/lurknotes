# Research: X11/EWMH внутри strict-снапа

**Тикет:** `.scratch/snap-store/issues/02-research-x11-under-strict.md`
**Дата:** 2026-10-28
**Ветка:** `research/x11-under-strict` (worktree `/tmp/opencode/wt-x11-under-strict`)
**Статус:** research завершён; код приложения не менялся.

## Окружение и метод

Проверка шла на живой сессии, а не только по документации:

- Ubuntu 24.04, GNOME 46, Wayland-сессия, XWayland `:0` (`/usr/bin/Xwayland :0 -rootless … -auth /run/user/1000/.mutter-Xwaylandauth.RRTCY3`), X.Org 23.2.6, x86_64.
- snapd 2.77.1; `snapcraft` не установлен.
- База `core24` rev 2124, контент-снап `gnome-46-2404` rev 177 (установлен rev 168), `mesa-2404` rev 1839.
- Первоисточники: Snapcraft docs, snapd source, EWMH/ICCCM, Xlib man, Mutter 46.0 source, `man Xwayland`.
- Локальные эксперименты:
  1. распаковка `core24`, `gnome-46-2404` и `mesa-2404` (`snap download` + `unsquashfs`, `readelf`);
  2. `snap run --shell` внутри strict-снапа `snapd-desktop-integration` (у него connected `x11`): `XOpenDisplay`, пути библиотек;
  3. GTK4-проба EWMH вне confinement (Mutter 46, XWayland);
  4. GTK3-проба EWMH **внутри strict-снапа**, включая клик через XTest.

Это не сборка самого LurkNotes: `snapcraft` в окружении нет, полный snap-смоук остаётся на execution-этап. Но все спорные механизмы (X11-сокет, auth, libX11, EWMH, фокус, клики, позиционирование) проверены отдельно.

## Короткий ответ

**Да, strict-снап с `plugs: [x11]` видит XWayland, и текущие X11/EWMH-трюки LurkNotes в нём работают.** Причины:

- `x11` — auto-connect интерфейс; ручной `snap connect` не нужен.
- `snapd` bind-mount'ит host-каталог `/tmp/.X11-unix` в private `/tmp` снапа; `DISPLAY` и `XAUTHORITY` наследуются, AppArmor разрешает cookie XWayland (`.mutter-Xwaylandauth.*`).
- `libX11.so.6` действительно **нет** ни в `core24`, ни в `gnome-46-2404`, но он приходит из `gpu-2404`/`mesa-2404`, который подтягивает GNOME-extension; `ctypes` есть в python 3.12 базы.
- `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `SKIP_PAGER`, `STICKY`, `_NET_WM_DESKTOP=0xFFFFFFFF`, `WM_HINTS.input=False`, `_NET_WM_USER_TIME=0` и `XMoveResizeWindow`/`XMoveWindow` приняты Mutter 46 и удерживаются — и вне снапа, и внутри strict-снапа (семантика «поверх/не в доке/на всех столах» следует из реализации Mutter, визуально док/overview не проверялись).
- Клик по окну с `input=False` доставляется окну, но клавиатурный фокус не забирает.

**Classic не нужен для X11/EWMH.** Confinement не меняет поведение WM: X11-протокол идёт целиком через сокет, AppArmor не разбирает EWMH-запросы. Если в реальной snap-сборке что-то сломается, это будут четыре вещи: отсутствующий XWayland, неподключённый `x11`, слетевший `GDK_BACKEND=x11` или пропавший `libX11`, а не «strict не умеет edge-окна».

## 1. Как strict-снап получает X11

### 1.1. Интерфейс и auto-connect

Snapcraft docs для `x11` прямо говорят: **Auto-connect: yes**, Transitional: yes, условие подключения — «если у снапа есть GUI, подключайте» ([Snapcraft: x11 interface](https://snapcraft.io/docs/reference/interfaces/x11-interface/)). В базовом объявлении snapd для `x11` нет запрета auto-connection; слот помечен `implicitOnClassic: true`, то есть на classic-системе слот предоставляет сама система, отдельный provider-снап не нужен ([snapd `interfaces/builtin/x11.go`](https://github.com/canonical/snapd/blob/master/interfaces/builtin/x11.go)).

Эмпирически на этой машине все установленные strict-снапы с `x11` подключены автоматически (в `snap connections` в колонке Notes стоит `-`, а не `manual`):

```text
x11  firefox:x11                    :x11  -
x11  snap-store:x11                 :x11  -
x11  snapd-desktop-integration:x11  :x11  -
...
```

То есть после `snap install lurknotes` соединение `lurknotes:x11 → :x11` появится само. Ручной вариант остаётся как аварийный: `sudo snap connect lurknotes:x11`.

### 1.2. Сокет и mount namespace

`x11`-бэкенд snapd добавляет в mount namespace снапа bind-mount **read-only**:

```text
/var/lib/snapd/hostfs/tmp/.X11-unix  →  /tmp/.X11-unix   (bind, ro)
```

Это видно в `MountConnectedPlug` ([x11.go](https://github.com/canonical/snapd/blob/master/interfaces/builtin/x11.go)). Проверка внутри strict-снапа `snapd-desktop-integration`:

```text
$ snap run --shell snapd-desktop-integration -c 'ls -l /tmp/.X11-unix/'
srwxrwxr-x 1 dev dev 0 Oct 28 18:08 X0
...
```

То есть XWayland-сокет `X0` доступен, хотя `/tmp` у снапа приватный. Abstract-сокет `@/tmp/.X11-unix/X0` тоже разрешён AppArmor-правилом интерфейса.

### 1.3. `DISPLAY` и `XAUTHORITY`

`DISPLAY` и `XAUTHORITY` не подменяются интерфейсом: `snap run` наследует окружение сессии (`osutil.OSEnvironment()`), а `XAUTHORITY` переопределяет только если смог смигрировать cookie из `/tmp` ([`cmd/snapd/cli/cmd_run.go`, `migrateXauthority`](https://github.com/canonical/snapd/blob/master/cmd/snapd/cli/cmd_run.go)). Для XWayland это не срабатывает (файл лежит в `/run/user/…`), и снап просто получает исходный путь.

Это безопасно, потому что AppArmor `x11`-plug'а разрешает ровно такие cookie:

```text
owner /run/user/[0-9]*/.Xauthority r,
owner /run/user/[0-9]*/.mutter-Xwaylandauth.* r,
owner /run/user/[0-9]*/mutter/Xauthority r,
owner /run/user/[0-9]*/xauth_* r,
```

(см. `x11ConnectedPlugAppArmor` в [x11.go](https://github.com/canonical/snapd/blob/master/interfaces/builtin/x11.go); плюс общая `<abstractions/X>`, которая покрывает Xorg-пути вроде `/run/user/*/gdm/Xauthority` — локальный `/etc/apparmor.d/abstractions/X`).

Проверка внутри strict-снапа:

```text
$ snap run --shell snapd-desktop-integration -c \
    'echo $DISPLAY; echo $XAUTHORITY; python3 -c "..."'
DISPLAY=:0
XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.RRTCY3
find_library: libX11.so.6
XOpenDisplay -> 469637808
ctypes OK
```

Cookie читается (`head` файла вернул `MIT-MAGIC-COOKIE-1`), `XOpenDisplay(None)` возвращает валидный pointer. Это прямой ответ на вопрос «видит ли strict-снап XWayland»: **да, при подключённом `x11`**.

### 1.4. Что говорит `x11` про безопасность

Документация и AppArmor-сниппет честно предупреждают: X11 не изолирует клиентов, поэтому интерфейс даёт доступ ко всем X-окнам (в том числе потенциальный keylogging). Для GUI-приложения это нормальная цена; подробнее — в разделе 5.

## 2. `libX11.so.6`, `ctypes` и GTK: что реально есть в базе/extension

### 2.1. `core24`

В распакованной `core24` rev 2124 есть:

- `/usr/bin/python3.12` (symlink `python3`), полный `python3.12`;
- `/usr/lib/python3.12/ctypes/` и `_ctypes.cpython-312-x86_64-linux-gnu.so`;
- `libffi.so.8` (нужен `_ctypes`).

`libX11.so.6` в `core24` **нет**; `libxcb`/`libXau`/`libXdmcp` тоже нет (проверено `find`/`ls` по распакованному base). `_ctypes` на Ubuntu 24.04 принадлежит пакету `libpython3.12-stdlib` — то есть `ctypes` доступен из базового python без `stage-packages`.

**Вывод:** `ctypes` — да, из `core24`. `libX11` — нет.

### 2.2. `gnome-46-2404`

В контент-снапе rev 177 (и в установленном rev 168) есть:

- `libgtk-4.so.1`, `libgdk-3.so`, GTK3/GTK4;
- `gi` для python 3.12: `usr/lib/python3/dist-packages/gi/_gi.cpython-312-x86_64-linux-gnu.so`;
- typelibs `Gtk-4.0.typelib`, `GdkX11-4.0.typelib`, `GdkX11-3.0.typelib`.

`libX11.so.6` в `gnome-46-2404` **нет** (при этом `libgtk-4.so.1` и `libgdk-3.so` имеют `NEEDED libX11.so.6` — проверено `readelf -d`). Значит, extension сам по себе libX11 не приносит.

### 2.3. Откуда libX11 берётся на самом деле: `gpu-2404` / `mesa-2404`

GNOME-extension для core24 наследует `GPUExtension` и добавляет content-plug `gpu-2404` с `default-provider: mesa-2404` ([snapcraft `gnome.py`](https://github.com/canonical/snapcraft/blob/main/snapcraft/extensions/gnome.py), [`gpu_extension.py`](https://github.com/canonical/snapcraft/blob/main/snapcraft/extensions/gpu_extension.py)). В `mesa-2404` rev 1839 лежит:

```text
/snap/mesa-2404/current/usr/lib/x86_64-linux-gnu/libX11.so.6 -> libX11.so.6.4.0
/snap/mesa-2404/current/usr/lib/x86_64-linux-gnu/libX11-xcb.so.1
```

GPU-wrapper (`gpu-2404-provider-wrapper`) добавляет `…/gpu-2404/usr/lib/x86_64-linux-gnu` в `LD_LIBRARY_PATH`. Проверка внутри strict-снапа:

```text
$ snap run --shell snapd-desktop-integration -c \
    'python3 -c "import ctypes; ctypes.CDLL(\"libX11.so.6\") ... /proc/self/maps"'
... /snap/snapd-desktop-integration/391/gpu-2404/usr/lib/x86_64-linux-gnu/libX11.so.6.4.0
```

То есть **libX11 приходит из mesa-2404 через gpu-2404**, а не из базы и не из GNOME-extension.

### 2.4. Нужен ли `stage-packages: [libx11-6]`?

Практический ответ:

- **Если используется GNOME-extension (планируемый путь LurkNotes) — не обязательно.** `gpu-2404` — жёсткая зависимость extension: без него падает `gpu-2404-wrapper`, а libX11 уже на `LD_LIBRARY_PATH`. `libgtk-4` всё равно требует libX11, так что любой GNOME-snap на core24 уже зависит от этого пути.
- **Если собирать без GNOME-extension** — `stage-packages: [libx11-6]` нужен, но одного staging недостаточно: каталог `$SNAP/usr/lib/$ARCH` не попадает в `LD_LIBRARY_PATH` автоматически (desktop-launch не добавляет `$SNAP/usr/lib/$ARCH`; gpu-wrapper добавляет только `gpu-2404`). Нужно либо добавить `$SNAP/usr/lib/$ARCH` в `LD_LIBRARY_PATH`/rpath, либо явно проверить `ctypes.CDLL("libX11.so.6")` в собранном снапе.
- `libx11-6` в 24.04 весит ~1.3 MB и тянет `libxcb1`, `libx11-data` (`apt-cache depends libx11-6`). Как fallback это дёшево, но при GNOME-extension он всё равно будет перекрыт libX11 из mesa (gpu-2404 идёт раньше в `LD_LIBRARY_PATH`).

**Рекомендация:** оставить GNOME-extension и добавить в сборочный smoke-test проверку `ctypes.CDLL("libX11.so.6")` + `XOpenDisplay`; `stage-packages` для libX11 не нужен, если сборка идёт с extension. Это же снимает риск «забыли gpu-2404».

### 2.5. Python, `gi` и `GDK_BACKEND`

`desktop-launch` из `gnome-46-2404` сам выставляет `PYTHONPATH` на `gnome-platform/usr/lib/python3.12` и `.../python3/dist-packages`, а также `GI_TYPELIB_PATH`. В strict-снапе `import gi; Gtk 3.24` работает без ручной настройки (проверено).

Важная деталь: тот же `desktop-launch` при наличии Wayland делает:

```bash
if [ "$wayland_available" = true ]; then
  export GDK_BACKEND="wayland"
  ...
fi
```

Поэтому в strict-снапе GTK по умолчанию выбрал **Wayland**: наша первая проба внутри снапа получила `GdkWaylandWindow` и упала на `get_xid()`. LurkNotes это уже учитывает: `src/lurkn/__main__.py` строкой 21 ставит `os.environ["GDK_BACKEND"] = "x11"` **до** импорта GTK. Это обязательный инвариант snap-сборки: если его убрать/перезаписать, приложение уйдёт в Wayland и `GdkX11`/`x11.py` сломаются.

## 3. EWMH-механика под Mutter 46 / XWayland

Ниже — по каждому пункту тикета: спецификация → поведение Mutter → локальная проверка. Проверки делались дважды: обычным GTK4-клиентом и GTK3-клиентом **внутри strict-снапа** (`snapd-desktop-integration`), с одинаковым набором вызовов, что и `src/lurkn/x11.py`.

### 3.1. `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `SKIP_PAGER`, `STICKY`

Спецификация EWMH §5.7: `_NET_WM_STATE_ABOVE` — «окно должно быть поверх большинства окон»; `SKIP_TASKBAR`/`SKIP_PAGER` — не показывать в taskbar/pager; `STICKY` — не двигать при скролле виртуального десктопа ([EWMH §5.7](https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html)).

Mutter 46 хранит эти состояния в `window->wm_state_above/skip_taskbar/skip_pager` и вычисляет слой:

```c
/* src/core/window.c, meta_window_get_default_layer() */
if (window->wm_state_above && !META_WINDOW_MAXIMIZED (window))
  return META_LAYER_TOP;
```

([Mutter 46 `window.c`](https://github.com/GNOME/mutter/blob/46.0/src/core/window.c)). Состояния принимаются и через `_NET_WM_STATE` client message (`meta_window_x11_client_message` в [`src/x11/window-x11.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-x11.c)).

Локально после `set_deck_hints`:

```text
_NET_WM_STATE(ATOM) = _NET_WM_STATE_SKIP_PAGER, _NET_WM_STATE_SKIP_TASKBAR,
                      _NET_WM_STATE_ABOVE, _NET_WM_STATE_STICKY,
                      _NET_WM_STATE_DEMANDS_ATTENTION
```

То же самое — внутри strict-снапа. `ABOVE` по коду Mutter действует и для X11-окна поверх Wayland-нативных окон: слой `META_LAYER_TOP` общий для композитора Mutter, а не отдельный X11-стек (визуально не проверяли).

`DEMANDS_ATTENTION` Mutter добавляет сам, когда окно мапится без фокуса и с `SKIP_TASKBAR`; это не ошибка и не snap-специфика (наблюдалось и вне снапа).

### 3.2. `_NET_WM_DESKTOP = 0xFFFFFFFF`

EWMH §5.5: `0xFFFFFFFF` означает «окно на всех десктопах» ([EWMH §5.5](https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html)). Mutter обрабатывает client message и выставляет `on_all_workspaces_requested` ([`window-x11.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-x11.c)).

Наблюдение:

```text
_NET_WM_DESKTOP(CARDINAL) = 4294967295
```

И вне, и внутри strict-снапа. На этой машине 2 рабочих стола (`_NET_NUMBER_OF_DESKTOPS=2`), значение принято без ошибок.

### 3.3. `WM_HINTS.input = False`

ICCCM: поле `input` в `WM_HINTS` сообщает WM модель ввода клиента; клиенты с Globally Active / No Input ставят `False` ([ICCCM, WM_HINTS](https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/ICCCM/icccm.html#wm_hints_property)). Mutter читает это в `reload_wm_hints`:

```c
/* src/x11/window-props.c */
window->input = hints->input;   /* при InputHint */
```

и учитывает в `meta_window_x11_is_focusable()` (`return window->input || priv->wm_take_focus;`) и в `meta_window_x11_focus()`:

```c
if (window->input || is_output_only_with_frame)
  meta_display_set_input_focus (...);
```

То есть при `input=False` Mutter **не вызывает `XSetInputFocus`** на это окно ([`window-x11.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-x11.c), [`window-props.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-props.c)).

Наблюдение: `WM_HINTS ... Client accepts input or input focus: False` сохраняется и вне, и внутри strict-снапа.

### 3.4. `_NET_WM_USER_TIME = 0`

EWMH §5.15: «специальное значение zero на только что замапленном окне можно использовать, чтобы окно не получало фокус при маппинге» ([EWMH §5.15](https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html)).

Mutter в `intervening_user_event_occurred()` явно проверяет:

```c
if ((window->net_wm_user_time_set && window->net_wm_user_time == 0) || ...)
  {
    meta_topic (..., "window %s explicitly requested no focus", ...);
    return TRUE;
  }
```

([`window.c`](https://github.com/GNOME/mutter/blob/46.0/src/core/window.c)). Свойство перечитывается и после маппинга (`reload_net_wm_user_time` в `window-props.c`).

Наблюдение: `_NET_WM_USER_TIME(CARDINAL) = 0`, окно не активируется. В пробе без `present()` `_NET_ACTIVE_WINDOW` остался `0x0`; клавиатурный фокус не переехал.

### 3.5. `XMoveWindow`, `XMoveResizeWindow` и позиция у края

Xlib: `XMoveWindow` на mapped-окне при наличии другого клиента с `SubstructureRedirectMask` на parent (это как раз WM) не двигает окно само, а генерирует `ConfigureRequest`; решение за WM ([Xlib `XMoveWindow`](https://www.x.org/releases/current/doc/libX11/libX11/libX11.html#XMoveWindow)). Mutter обрабатывает `ConfigureRequest` в `meta_window_x11_configure_request()` → `meta_window_move_resize_request()` ([`window-x11.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-x11.c)) и для нормального окна двигает его.

Проверка вне снапа (окно undecorated, rect `(2580, 64, 300, 1856)` при экране 2880×1920 и workarea `132,64,2748,1856`):

```text
Absolute upper-left X: 2580
Absolute upper-left Y: 64
Width: 300
Height: 1856
```

Проверка **внутри strict-снапа** (rect `(2380, 64, 200, 400)`; GTK3 сам поменял размер после мапа, но позиция точная):

```text
Absolute upper-left X: 2380
Absolute upper-left Y: 64
Map State: IsViewable
```

То есть координаты — физические X11-пиксели, `XMoveResizeWindow` работает и в снапе; `XMoveWindow` идёт тем же путём `ConfigureRequest` и отдельно проверен: окно переехало в `(2200, 100)`, размер не изменился (600×800 — это GTK default 300×400 logical при scale 2).

**Нюанс позиционирования:** если окно **декорировано**, Mutter добавляет frame extents. В пробе с обычным `Gtk.Window`:

```text
_NET_FRAME_EXTENTS(CARDINAL) = 0, 0, 74, 0
запрос (100,200) → клиент (132,274)
```

74 px сверху — это titlebar (37 logical × 2), а x=132 — clamp к workarea (левая панель). LurkNotes делает `set_decorated(False)` для strip и panel, поэтому у него frame extents нулевые и rect совпадает точно; в strict-снапе это поведение сохраняется (наша strict-проба тоже была undecorated и попала в запрошенную точку).

**Вывод по позиционированию:** `XMoveWindow`/`XMoveResizeWindow` пригодны; никакой snap-специфики нет. Единственное требование — окна должны оставаться undecorated (уже так) и координаты считаться в физических пикселях (уже так).

### 3.6. Фокус и клики при `input=False` (включая клик)

Теория:

- `WM_HINTS.input=False` говорит WM не давать окну клавиатурный фокус; на X11 указательные события доставляются окну под указателем независимо от клавиатурного фокуса.
- Mutter при клике вызывает `meta_window_focus()`, но для X11-окна с `input=False` `meta_window_x11_focus()` пропускает `XSetInputFocus` (см. 3.3). Значит, клик не должен «утащить» клавиатуру.

Проверка внутри strict-снапа: окно с `input=False`, `_NET_WM_USER_TIME=0`, `ABOVE`, клик через `XTestFakeButtonEvent` в его центр:

```text
probe: clicked 60.0 50.0
before: _NET_ACTIVE_WINDOW = 0xe00003
after:  _NET_ACTIVE_WINDOW = 0xe00003
```

Клик доставлен GTK-виджету, `_NET_ACTIVE_WINDOW` не переключился на пробное окно. В другом прогоне (без других окон) active был `0x0`. То есть клавиатурный фокус не захвачен.

Одна наблюдённая странность: после клика на окне появился `_NET_WM_STATE_FOCUSED`, хотя `_NET_ACTIVE_WINDOW` не изменился. Это внутренняя метка Mutter (display focus vs. фактический X input focus); приложение для проверки фокуса использует `X11.has_focus()` → `_NET_ACTIVE_WINDOW`, а не `_NET_WM_STATE_FOCUSED` и не `Gtk.Window.is_active()`, поэтому его логика (Esc, focus guard) остаётся корректной. Помечаю это как локальное наблюдение, а не как гарантию спецификации.

Когда панель открывается, приложение делает `set_input(xid, True)` + `allow_focus(xid)` (удаляет `_NET_WM_USER_TIME`), и `present()` уже может активировать окно — это тоже WM-поведение, одинаковое в снапе и вне его.

## 4. Что именно проверено внутри strict-снапа

Сводная таблица (✅ — проверено локально, 📄 — подтверждено первоисточником):

| Вопрос | Результат | Чем подтверждено |
|---|---|---|
| X11-дисплей виден | ✅ | `XOpenDisplay` в strict-снапе вернул pointer; `DISPLAY=:0` |
| XWayland cookie читается | ✅ | `XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.RRTCY3`, чтение файла |
| `x11` auto-connect | ✅📄 | docs «Auto-connect: yes»; `snap connections` без `manual` |
| `/tmp/.X11-unix` доступен | ✅📄 | `ls` в снапе; mount из `x11.go` |
| `_NET_WM_STATE_*` | ✅📄 | состояния в `xprop`; Mutter `window.c`/`window-x11.c` |
| `_NET_WM_DESKTOP=0xFFFFFFFF` | ✅📄 | `xprop` = 4294967295; EWMH §5.5 |
| `WM_HINTS.input=False` | ✅📄 | `xprop` False; `reload_wm_hints`, `meta_window_x11_focus` |
| `_NET_WM_USER_TIME=0` | ✅📄 | `xprop` 0, нет активации; EWMH §5.15, Mutter |
| `XMove*Window` | ✅📄 | точный rect вне и внутри снапа; Xlib + Mutter |
| Клик при `input=False` | ✅ | XTest-клик доставлен, active не изменился |
| `libX11.so.6` | ✅ | `gpu-2404/.../libX11.so.6.4.0` в `/proc/self/maps` |
| `ctypes` | ✅ | `_ctypes` + `libffi` в `core24`; импорт в снапе |
| GTK4/GdkX11/`gi` | ✅/⚠️ | typelibs `Gtk-4.0`/`GdkX11-4.0` и `_gi` есть в `gnome-46-2404`; GTK3-проба запускалась в снапе, GTK4+PyGObject — только вне |

## 5. Autoconnection и review

- **Auto-connect:** да, `x11` не требует ручного подтверждения. После установки соединение появляется само; `snap connect` нужен только если пользователь/система его разорвали. Это подтверждается docs и `snap connections` на живой системе.
- **Review:** по доступной документации и практике `x11` не относится к super-privileged интерфейсам, требующим отдельного одобрения Store ([Super-privileged interfaces](https://snapcraft.io/docs/explanation/interfaces/super-privileged-interfaces/)); публичные снапы (Firefox, Slack, LibreOffice, Snap Store) используют его с auto-connect. Практического «ручного ревью из-за x11» ожидать не нужно. (Страница super-privileged не перечисляет полный список, поэтому это вывод по совокупности источников, а не дословная цитата политики.)
- **Но:** `x11` — широкий интерфейс. Документация прямо говорит, что X11 не предотвращает eavesdropping и вмешательство приложений друг в друга. Пользователь увидит `x11` в разрешениях снапа; в описании стоит честно указать, что это GUI-приложение, работающее через X11/XWayland.
- **`wayland`:** GNOME-extension добавляет и `wayland`, и `x11`; оба auto-connect. Приложение всё равно принудительно идёт в X11, так что `wayland` здесь не используется, но и не мешает. Убирать его из extension-сборки не требуется.

## 6. Что писать про X11-требование

Предлагаемая формулировка (README/листинг/описание snap):

> **Requirements:** LurkNotes is an X11 client and needs an X11 or XWayland session. On Ubuntu 24.04 with GNOME, XWayland is enabled by default. A native Wayland session without XWayland is not supported.

По-русски:

> Приложению нужен сеанс X11 или XWayland. В Ubuntu 24.04 с GNOME XWayland включён по умолчанию; при отключённом XWayland приложение не запустится. Нативного Wayland-режима нет.

В `snapcraft.yaml`:

- `base: core24`, `confinement: strict`;
- `plugs: [x11]` — либо явно, либо через GNOME-extension (extension добавляет `desktop`, `desktop-legacy`, `opengl`, `wayland`, `x11`, `gsettings`);
- **не** добавлять `classic` ради X11 — это ничего не меняет;
- сохранить `GDK_BACKEND=x11` в `__main__.py` (уже есть) и не перетирать его в command-chain;
- `assumes: [snapd2.43]` приходит от extension; отдельного `assumes` для x11 не нужно;
- в описании не обещать «Wayland support»; писать «runs through XWayland on Wayland sessions».

Диагностика для execution-этапа (если snap не запускается):

1. `snap connections lurknotes | grep x11` — соединение есть?
2. `snap run --shell lurknotes -c 'echo $DISPLAY; echo $XAUTHORITY; ls /tmp/.X11-unix'`.
3. `snap run --shell lurknotes -c 'python3 -c "import ctypes; ctypes.CDLL(\"libX11.so.6\"); print(\"ok\")"'`.
4. Проверить, что `GDK_BACKEND=x11` (иначе GTK уйдёт в Wayland; см. 2.5).

## 7. Если strict всё-таки не воспроизведёт поведение: что именно сломается

По результатам проверки **EWMH-часть не ломается**. Возможные точки отказа и что остаётся:

| Симптом | Причина | Лечение | Остаётся ли classic? |
|---|---|---|---|
| `XOpenDisplay` = NULL, «нет дисплея» | XWayland выключен / нет `DISPLAY` | включить XWayland; документировать требование | Нет: classic не создаёт X-сервер |
| `XOpenDisplay` = NULL при working XWayland | `x11` не подключён, `/tmp/.X11-unix` не смонтирован | `snap connect lurknotes:x11` | Нет |
| Ошибка авторизации X11 | `XAUTHORITY` не проброшен/не разрешён | проверить env и AppArmor; для GNOME путь `.mutter-Xwaylandauth.*` уже разрешён | Нет |
| `libX11.so.6: cannot open` | нет `gpu-2404`/mesa или сборка без extension | подключить `gpu-2404`, либо stage `libx11-6` + `LD_LIBRARY_PATH` | Нет |
| `GdkWaylandWindow has no get_xid` | GTK выбрал Wayland | вернуть `GDK_BACKEND=x11` до импорта GTK | Нет |
| Окно не поверх/не sticky | hints не применились | проверить, что `set_deck_hints` вызывается после мапа (settle) | Нет |
| Окно не на краю | decorations/frame extents или неверный scale | `set_decorated(False)`, физические пиксели | Нет |

**Classic не является fallback для этой задачи.** Classic меняет файловый/AppArmor-доступ, но не поведение Mutter и не наличие XWayland. Если когда-нибудь понадобится classic, это будет из-за других требований (например, запись в host-конфиги вне snap), а не из-за EWMH. Альтернативный механизм — `zwlr_layer_shell_v1` — в Mutter 46 недоступен (спека уже фиксирует это, §16/«Layer-shell недоступен»), а GNOME Shell extension вне scope.

## 8. Остающиеся риски и неуверенность

1. **Нет полной сборки LurkNotes.** `snapcraft` не установлен; проверены GTK3-проба в strict-снапе и GTK4-проба вне снапа, но не GTK4 + PyGObject + `x11.py` в одном snap-процессе. Это главный оставшийся шаг execution-этапа.
2. **Autostart.** Как именно snapd запускает autostart в GNOME-сессии и есть ли в этот момент `DISPLAY`/`XAUTHORITY` — не проверялось (это тикет про автозапуск, не про X11). Риск: если autostart пойдёт через systemd user unit без графического окружения, `XOpenDisplay` упадёт. Нужен runtime-тест.
3. **Дробное масштабирование и multi-monitor.** Проверен один монитор 2880×1920 при scale 2. Поведение XWayland при fractional scaling — существующий риск X11-релиза, не усиленный snap'ом; нужен тест на нескольких мониторах.
4. **Xorg-сессия (не XWayland).** AppArmor `<abstractions/X>` покрывает `/run/user/*/gdm/Xauthority`, но локально проверен только XWayland. Для заявленного TA (Ubuntu 24.04 GNOME, Wayland) это не блокер.
5. **Store review.** Формального документа «x11 не требует ревью» нет; вывод основан на docs (auto-connect), списке super-privileged и практике публичных снапов. Если Store внезапно запросит обоснование — в описании уже будет X11-требование.
6. **`_NET_WM_STATE` применяется client message'ами.** EWMH §5.7 говорит, что клиент, желающий изменить состояние, MUST послать `_NET_WM_STATE` client message, а WM SHOULD учитывать `_NET_WM_STATE` при маппинге withdrawn-окна; свойство `_NET_WM_STATE` ведёт WM. Приложение отправляет сообщения до мапа и переприменяет их в `_on_*_map`/`settle`; post-map вариант проверен и работает. Теоретически pre-map сообщения могут быть проигнорированы (окно ещё не управляется), поэтому возможен короткий кадр без `ABOVE`/`SKIP_TASKBAR`; это уже текущее поведение deb-релиза, не регрессия снапа. Если захочется убрать — выставлять `_NET_WM_STATE` ещё и свойством до мапа (продуктовое изменение, вне этого тикета).
7. **`DEMANDS_ATTENTION` на мапе.** Mutter добавляет его окну без фокуса/skip-taskbar; наблюдалось и вне снапа. Косметика, но стоит проверить, не мигает ли иконка в доке.
8. **Визуальные эффекты `SKIP_TASKBAR`/`SKIP_PAGER`/`STICKY`/all-desktops не проверялись глазами.** Подтверждено, что Mutter выставляет и удерживает свойства, и что в его коде есть соответствующая обработка; поведение дока/overview и переключение рабочих столов стоит проверить в execution-этапе.

## 9. Источники

Первоисточники (проверены 2026-10-28):

- Snapcraft docs, x11 interface — <https://snapcraft.io/docs/reference/interfaces/x11-interface/> (Auto-connect: yes, transitional, condition to connect).
- snapd, `interfaces/builtin/x11.go` — <https://github.com/canonical/snapd/blob/master/interfaces/builtin/x11.go> (mount `/tmp/.X11-unix`, AppArmor, `implicitOnClassic`).
- snapd, `cmd/snapd/cli/cmd_run.go` (`migrateXauthority`) — <https://github.com/canonical/snapd/blob/master/cmd/snapd/cli/cmd_run.go>.
- AppArmor `abstractions/X` (локальный файл `/etc/apparmor.d/abstractions/X`).
- Snapcraft `gnome` extension — <https://github.com/canonical/snapcraft/blob/main/snapcraft/extensions/gnome.py>; `gpu_extension.py` — <https://github.com/canonical/snapcraft/blob/main/snapcraft/extensions/gpu_extension.py>.
- EWMH (wm-spec): §5.5 `_NET_WM_DESKTOP`, §5.7 `_NET_WM_STATE`, §5.15 `_NET_WM_USER_TIME` — <https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html>.
- ICCCM, WM_HINTS (`input`) — <https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/ICCCM/icccm.html#wm_hints_property>.
- Xlib, `XMoveWindow` — <https://www.x.org/releases/current/doc/libX11/libX11/libX11.html#XMoveWindow>.
- Mutter 46.0: [`src/x11/window-x11.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-x11.c), [`src/x11/window-props.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/window-props.c), [`src/core/window.c`](https://github.com/GNOME/mutter/blob/46.0/src/core/window.c), [`src/x11/meta-x11-display.c`](https://github.com/GNOME/mutter/blob/46.0/src/x11/meta-x11-display.c).
- XWayland man page (локально, xwayland 23.2.6): «Xwayland is an X server and a Wayland client… usually spawned automatically… runs rootless».
- Snap Store, super-privileged interfaces — <https://snapcraft.io/docs/explanation/interfaces/super-privileged-interfaces/>.

Локальные артефакты проверки (вне репозитория, `/tmp/opencode/`): `ewmh_probe.py` (GTK4), `ewmh_click_probe3.py` (GTK3), `click.py`, распакованные `core24-root`, `gnome-root`, `mesa-2404`.

## 10. Итог для карты

- Тикет 02 можно закрывать как **resolved: strict + x11 воспроизводит текущее поведение**; classic для X11 не нужен.
- В execution-этап добавить: `plugs: [x11]` (или GNOME-extension), smoke-test `XOpenDisplay`/`libX11` в собранном снапе, проверку autostart-окружения и multi-monitor/fractional scaling.
- В листинг — требование X11/XWayland, без обещания нативного Wayland.
