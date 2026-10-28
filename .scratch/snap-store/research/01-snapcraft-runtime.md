# Snapcraft-рецепт для PyGObject/GTK4: результаты исследования

**Машина:** Ubuntu 24.04 (noble), GNOME Shell 46, сессия Wayland + XWayland (`DISPLAY=:0`), x86_64, snapd 2.77.1. `snapcraft` и LXD не установлены, `sudo` требует пароль. Свободно ~790 ГБ, 22 CPU, 15 ГБ RAM.
**Дата проверки:** 2026-10-28.
**Метод:** `snap info`, `snap download` + `unsquashfs` (base `core24`, runtime `gnome-46-2404`, GPU `mesa-2404`), чтение исходников Snapcraft / craft-parts / gnome-sdk / snapcraft-desktop-integration, проверка runtime-стека на хосте (вне confinement) с библиотеками из скачанных снапов, `snapcraft expand-extensions` из исходников Snapcraft (HEAD) в одноразовом venv. **Реальная сборка снапа не запускалась** (нет `snapcraft`, LXD и пароля sudo) — это главная граница достоверности.

---

## Краткий вердикт

1. **База и расширение:** `base: core24` + `extensions: [gnome]` — правильная и достаточная комбинация. Extension подключает `gnome-46-2404` (GTK/PyGObject/GIR), `mesa-2404` (GPU и X11-библиотеки), `gtk-common-themes`, добавляет `desktop-launch`, plugs и build-SDK. Ничего из этого не надо перечислять в `stage-packages`.
2. **`python` plugin не обязателен, но удобен.** Runtime-интерпретатор для strict-снапа на core24 — это Python 3.12.3 из base (`/usr/bin/python3.12`); `gi` берётся из content-снапа через `PYTHONPATH`. `stage-packages: [python3-gi, gir1.2-gtk-4.0]` не нужны и вредны (дубль GTK другой версии). `libx11-6` тоже не нужен: libX11 приходит из `mesa-2404`.
3. **GTK в снапе будет не 4.14, а 4.20.4** (rev 177 `gnome-46-2404` на момент проверки). Это не тот GTK, против которого приложение проверялось на хосте (4.14.5), и версия может меняться при обновлении content-снапа независимо от релиза приложения.
4. **`GDK_BACKEND=x11` уже выставляется самим приложением** в `src/lurkn/__main__.py:21` до импорта GTK. Дополнительно в `snapcraft.yaml` стоит задать `DISABLE_WAYLAND=1` и `GDK_BACKEND=x11`: `desktop-launch` иначе принудительно ставит Wayland.
5. **Команда/desktop/icon:** `command: bin/lurknotes` (console script от `python` plugin), `desktop:` указывает на файл **внутри prime** (`usr/share/applications/lurknotes.desktop`), поэтому desktop-файл кладётся отдельной `dump`-частью; `icon:` — путь к SVG/PNG в проекте, Snapcraft сам копирует его в `meta/gui/icon.svg` и переписывает `Icon=` в desktop-файле.
6. **X11-библиотеки — ключевая находка:** ни base `core24`, ни `gnome-46-2404` не содержат `libX11.so.6`; она лежит в `mesa-2404`, который extension монтирует как `gpu-2404`, а `gpu-2404-wrapper` добавляет его `usr/lib` в `LD_LIBRARY_PATH`. То есть X11-стек снапа **зависит от подключения `gpu-2404`/`mesa-2404`**.
7. **Сборка:** Snapcraft 9.2.1 (classic snap) + LXD 6.10 (по умолчанию на Linux) либо Multipass; `--destructive-mode` возможен на 24.04, но требует root и не рекомендуется. На этой машине первый шаг требует интерактивного sudo владельца.
8. Кандидат `snapcraft.yaml` прошёл JSON-схему Snapcraft и `snapcraft expand-extensions`; расширенный конфиг содержит ожидаемые `command-chain: [gpu-2404-wrapper, desktop-launch]`, plugs и `SNAP_DESKTOP_RUNTIME`.

---

## 1. Геометрия `core24` + `gnome`

### Что откуда берётся

| Слой | Snap / источник | Что даёт | Проверено |
|---|---|---|---|
| Base | `core24` (rev 2124) | Ubuntu 24.04 userland; Python 3.12.3 в `/usr/bin/python3.12`; **нет** `gi`, нет ни одного `.typelib` | `snap download core24`, `unsquashfs`, запуск `usr/bin/python3.12 --version` → `3.12.3`; `find core24 -name '*.typelib'` → 0 |
| Runtime | `gnome-46-2404` (rev 177, 646 МБ) | GTK **4.20.4**, PyGObject **3.56.2**, typelibs `Gtk-4.0`, `Gdk-4.0`, `GdkX11-4.0`, `Graphene-1.0`, `Pango-*`; Python 3.12.3; часть X11-библиотек; темы/иконки/шрифты; монтируется в `$SNAP/gnome-platform` | `snap download gnome-46-2404` + `unsquashfs`; `strings libgtk-4.so…` → `4.20.4`; `gi.require_version` + `Gtk.get_micro_version()` → `20`; наличие `Gtk-4.0.typelib` |
| Build SDK | `gnome-46-2404-sdk` (rev 206, 656 МБ) | Заголовки, pkg-config, gir, build-tools; **только на время сборки**; extension прописывает его как build-snap | `snap info gnome-46-2404-sdk`; `snapcraft expand-extensions` показал `gnome/sdk: build-snaps: [gnome-46-2404-sdk]` |
| GPU/X11 | `mesa-2404` (rev 1839, 422 МБ) | Mesa/EGL/GBM **и** `libX11.so.6`, `libXext`, `libXfixes`, `libXdamage`, `libxcb*`, `libXau`, `libXdmcp` | `snap download`/`unsquashfs`/`ls /snap/mesa-2404/current/usr/lib/x86_64-linux-gnu` |
| Темы | `gtk-common-themes` | GTK/icon/sound themes; `data-dir/themes` и т. п. | extension source + `snap list` |

Версия установленного на хосте `gnome-46-2404` — rev 168 с GTK **4.18.6**, в Store уже rev 177 с **4.20.4**: content-снап обновляется отдельно от приложения (см. риски).

### Что именно делает extension

Первоисточник — `snapcraft/extensions/gnome.py` (Snapcraft, коммит `cdab9e6…`):

- для core24 выбирает `gnome-46-2404` / `gnome-46-2404-sdk`
  ([`_SDK_SNAP`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py#L29-L33));
- каждому app добавляет `command-chain: [snap/command-chain/desktop-launch]` и plugs `desktop`, `desktop-legacy`, `gsettings` (core24), `opengl`, `wayland`, `x11`
  ([`get_app_snippet`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py#L94-L122));
- на уровне проекта добавляет content-plugs `gnome-46-2404` → `$SNAP/gnome-platform`, `gtk-3-themes`/`icon-themes`/`sound-themes`, `desktop` с `mount-host-font-cache: false`, env `SNAP_DESKTOP_RUNTIME=$SNAP/gnome-platform`, `GTK_USE_PORTAL=1`, layout-биндинги и `configure`-hook
  ([`get_root_snippet`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py#L160-L230));
- в build-environment каждого part прокидывает `SNAPCRAFT_GNOME_SDK`, `PATH`, `LD_LIBRARY_PATH`, `PKG_CONFIG_PATH`, `GI_TYPELIB_PATH`, `PYTHONPATH` и т. д.
  ([`get_part_snippet`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py#L275-L360));
- добавляет part `gnome/sdk` с `build-snaps: [gnome-46-2404-sdk]`
  ([`get_parts_snippet`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py#L365-L385)).

GNOME extension наследует `GPUExtension`, поэтому дополнительно:

- plug `gpu-2404` (`target: $SNAP/gpu-2404`, `default-provider: mesa-2404`);
- `command-chain: [snap/command-chain/gpu-2404-wrapper]` **перед** `desktop-launch`;
- layout для `libdrm`, `drirc.d`, `X11/XErrorDB`;
- part `gpu/wrapper` и `gpu/cleanup`
  ([`gpu_extension.py`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gpu_extension.py#L50-L140)).

Фактический результат `snapcraft expand-extensions` для кандидата (сокращённо):

```yaml
apps:
  lurknotes:
    command: bin/lurknotes
    desktop: usr/share/applications/lurknotes.desktop
    plugs: [desktop, desktop-legacy, gsettings, opengl, wayland, x11]
    environment:
      DISABLE_WAYLAND: '1'
      GDK_BACKEND: x11
    command-chain:
      - snap/command-chain/gpu-2404-wrapper
      - snap/command-chain/desktop-launch
environment:
  SNAP_DESKTOP_RUNTIME: $SNAP/gnome-platform
  GTK_USE_PORTAL: '1'
assumes: [snapd2.43]
```

Вывод: `stage-packages` для GTK/PyGObject/X11 не нужны; extension закрывает и build-time, и runtime.

---

## 2. Откуда берутся PyGObject, GTK4 и libX11

### PyGObject и typelibs

- Base `core24` **не содержит** `gi`: в `core24/usr/lib/python3/dist-packages` нет каталога `gi`, `find core24 -name '*.typelib'` даёт 0. Есть только Python 3.12.3 и stdlib.
- Content-снап `gnome-46-2404` содержит:
  - `usr/lib/python3/dist-packages/gi/_gi.cpython-312-x86_64-linux-gnu.so` (PyGObject **3.56.2**);
  - `usr/lib/x86_64-linux-gnu/girepository-1.0/Gtk-4.0.typelib`, `Gdk-4.0.typelib`, `GdkX11-4.0.typelib`, `Graphene-1.0.typelib`, `Pango-1.0.typelib` и др.
- В исходнике content-снапа эти пакеты явно в `stage-packages`: `python3-gi`, `python3.12-minimal`, `gir1.2-*`
  ([gnome-sdk, ветка gnome-46-2404](https://github.com/ubuntu/gnome-sdk/blob/gnome-46-2404/snap/snapcraft.yaml#L225-L245)).

На хосте (Python 3.12.3, как в base) с `PYTHONPATH`/`GI_TYPELIB_PATH`/`LD_LIBRARY_PATH` из content-снапа:

```
GTK 4 20 4
PyGObject 3.56.2
display X11Display
libX11 ok
```

То есть **Python из base + `gi` из content-снапа работают вместе** (одинаковый ABI cp312).

### libX11 — не в base и не в GNOME-снапе

Проверка `unsquashfs`/`find`:

| Библиотека | `core24` | `gnome-46-2404` | `mesa-2404` |
|---|---|---|---|
| `libX11.so.6` | нет | **нет** | да |
| `libXext`, `libXfixes`, `libXdamage` | нет | нет | да |
| `libxcb`, `libXau`, `libXdmcp` | нет | нет | да |
| `libXcomposite`, `libXrender`, `libXcursor`, `libXrandr`, `libXi`, `libXinerama` | нет | да | нет |

При этом `libgtk-4.so.1.2000.4` из content-снапа имеет `NEEDED libX11.so.6` (`readelf -d`). Значит, X11-backend GTK в снапе может загрузиться только если `libX11` виден загрузчику.

Как он туда попадает:

- content-плагин `gpu-2404` монтирует `mesa-2404` в `$SNAP/gpu-2404`;
- `snap/command-chain/gpu-2404-wrapper` вызывает `gpu-2404-provider-wrapper`, который добавляет `$SNAP/gpu-2404/usr/lib/x86_64-linux-gnu` в `LD_LIBRARY_PATH` (и `dri`, `vdpau`, `gbm`).
  См. [`gpu-2404-wrapper`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gpu_extension.py#L107-L125) и сам wrapper в `mesa-2404` (`/snap/mesa-2404/current/bin/gpu-2404-provider-wrapper`);
- `desktop-launch` добавляет в `LD_LIBRARY_PATH` каталоги `$SNAP/gnome-platform/usr/lib/...`
  ([`common/desktop-exports`](https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/common/desktop-exports#L73-L76)).

**Следствие:** `stage-packages: [libx11-6]` не нужен. Более того, он, скорее всего, был бы бесполезен: `desktop-launch` не добавляет `$SNAP/usr/lib/$ARCH` в `LD_LIBRARY_PATH`, а `ctypes.CDLL("libX11.so.6")` и GTK ищут библиотеку по этому пути. Единственный надёжный источник — `mesa-2404` через `gpu-2404`.

**Неуверенность:** это наблюдение для rev 177 (и rev 168 на хосте). Если Canonical начнёт класть `libX11` в `gnome-46-2404`, картина изменится; если `gpu-2404` не подключится, приложение не запустится ни через GTK X11, ни через `ctypes`.

---

## 3. `python` plugin или `dump` + `stage-packages`

### Что делает `python` plugin на core24

- Для strict/devmode на core24 Snapcraft считает системным интерпретатором **`/usr/bin/python3.12` из base**; для classic и core26 Python надо бандлить
  ([`python_common.py`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/plugins/python_common.py#L36-L90), [docs: Python plugin > Dependencies](https://github.com/canonical/snapcraft/blob/main/docs/reference/plugins/_python_common.rst)).
- Плагин создаёт venv **в корне part install**, то есть в `$SNAP`: `$SNAP/bin/python3`, `$SNAP/lib/python3.12/site-packages`, `$SNAP/pyvenv.cfg`
  ([`base.py`](https://github.com/canonical/craft-parts/blob/8de841e9b129060ced0693b746855ce0c131f5e5/craft_parts/plugins/base.py): `_get_venv_directory` → `part_install_dir`, `-m venv ${PARTS_PYTHON_VENV_ARGS}`; `PARTS_PYTHON_VENV_ARGS` по умолчанию пуст, `--system-site-packages` **не** передаётся).
- `pip install .` ставит пакет в venv, console script `lurknotes` появляется в `$SNAP/bin/lurknotes`, shebang переписывается на `#!/usr/bin/env python3`
  ([`base.py`, `_get_rewrite_shebangs_commands`](https://github.com/canonical/craft-parts/blob/8de841e9b129060ced0693b746855ce0c131f5e5/craft_parts/plugins/base.py); `python_common.get_script_interpreter` для core24 возвращает `None` → дефолт).
- venv изолирован от system site-packages, поэтому `gi` появляется только потому, что `desktop-launch` добавляет в `PYTHONPATH`:
  - `$SNAP_DESKTOP_RUNTIME/usr/lib/python3.12`;
  - `$SNAP_DESKTOP_RUNTIME/usr/lib/python3/dist-packages`
  ([`gnome/launcher-specific`](https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/gnome/launcher-specific#L20-L26); в собранном снапе `%WITH_PYTHON%` = `3.12`).

Проверка на хосте: venv + `pip install` проекта + `PYTHONPATH`/`LD_LIBRARY_PATH` content-снапа → `import lurkn.app` и `lurknotes --version` работают.

### Нужен ли он

Функционально — **нет**: приложение чистый Python без PyPI-зависимостей (`pyproject.toml`: `dependencies = []`). Достаточно `dump`-части и запуска `python3 -m lurkn` базовым интерпретатором. Но `python` plugin даёт:

- канонический console script `bin/lurknotes`;
- установку пакета в `site-packages` вместо копирования исходников в `$SNAP/src`;
- автоматическую обработку shebang/venv.

Цена: `pip install .` с build isolation тянет `setuptools>=68` с PyPI (в build-контейнере нужна сеть); venv добавляет `pip`/`setuptools`/`wheel` в снап (~15 МБ).

**Рекомендация:** оставить `python` plugin как основной вариант; если нужна полностью офлайн-сборка — заменить на `dump` + обёртку `bin/lurknotes`:

```sh
#!/bin/sh
export PYTHONPATH="$SNAP/src"
exec /usr/bin/python3.12 -m lurkn "$@"
```

Оба варианта дают одинаковый runtime-стек (`python3 -m lurkn` проверен на репозитории).

### Почему не `stage-packages: [python3-gi, gir1.2-gtk-4.0, libx11-6]`

- `python3-gi`/`gir1.2-gtk-4.0` из архива noble принесут GTK **4.14** и его зависимости в сам снап (сотни МБ), которые будут конкурировать с GTK 4.20.4 из `gnome-46-2404`. Это ровно тот случай, о котором предупреждает документация extension: не бандлить библиотеки, которые даёт content-снап
  ([GNOME extension > Library cleanup](https://github.com/canonical/snapcraft/blob/main/docs/reference/extensions/gnome-extension.rst)).
- `libx11-6` не нужен (см. §2), а без явного `LD_LIBRARY_PATH` на `$SNAP/usr/lib/$ARCH` staged-копия всё равно не будет найдена.
- `python3.12-minimal` в `stage-packages` тоже не нужен: core24 strict использует интерпретатор base. Пример в туториале Snapcraft с `stage-packages: [python3-minimal, python3.12-minimal]` — наследие core22/переноса, для core24 он избыточен.

---

## 4. Команда, desktop-файл и иконка

### Команда

```yaml
apps:
  lurknotes:
    command: bin/lurknotes
```

`bin/lurknotes` — console script, который создаёт `python` plugin из `[project.scripts] lurknotes = "lurkn.__main__:main"` (`pyproject.toml`).

### Desktop-файл

Ключ `apps.<app>.desktop` принимает путь **относительно prime**, а не исходников
([docs: Configure package information](https://github.com/canonical/snapcraft/blob/main/docs/how-to/crafting/configure-package-information.rst)). `python` plugin не копирует `packaging/` в prime, поэтому нужен отдельный `dump`-part:

```yaml
  desktop-assets:
    plugin: dump
    source: packaging
    organize:
      lurknotes.desktop: usr/share/applications/lurknotes.desktop
      lurknotes.svg: usr/share/icons/hicolor/scalable/apps/lurknotes.svg
```

```yaml
    desktop: usr/share/applications/lurknotes.desktop
```

Snapcraft при priming:

- переписывает первый токен `Exec=` на имя app (у нас app = snap = `lurknotes`, поэтому остаётся `lurknotes`);
- переписывает `Icon=` на `${SNAP}/meta/gui/icon.svg`, если задан top-level `icon:`;
- кладёт результат в `meta/gui/lurknotes.desktop`
  ([`desktop_file.py`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/desktop_file.py#L71-L100), [`setup_assets.py`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/setup_assets.py#L279-L329)).

Исходный `packaging/lurknotes.desktop` (`Exec=lurknotes`, `Icon=lurknotes`, `Categories=Utility;`) подходит без правок. `Name=Lurk Notes` не совпадает с листинговым `LurkNotes` — это вопрос текстов листинга (тикет 07), не рецепта.

### Иконка

```yaml
icon: packaging/lurknotes.svg
```

Top-level `icon` — это и иконка Store, и источник для `Icon=` в desktop-файле. Snapcraft копирует файл в `meta/gui/icon.<ext>`
([`_finalize_icon`](https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/setup_assets.py#L279-L329)). Требования из модели Snapcraft: сторона 40–512 px, рекомендуется 256×256, файл < 256 КБ. Текущий `packaging/lurknotes.svg` — 128×128; для Store, возможно, понадобится PNG 256×256 (проверить в тикете 07). **Не проверено:** примет ли Store SVG в качестве листинговой иконки.

Альтернатива — legacy `snap/gui/lurknotes.desktop` + `snap/gui/lurknotes.svg` без ключей `desktop:`/`icon:`; Snapcraft копирует `snap/gui` в `meta/gui`. Современная документация рекомендует `desktop:`/`icon:`, этот вариант и выбран.

---

## 5. `GDK_BACKEND=x11` и X11-библиотеки

### Что уже делает приложение

`src/lurkn/__main__.py`:

```python
def main(argv=None):
    # Spec §9.1: must happen before GTK/GDK is imported anywhere.
    os.environ["GDK_BACKEND"] = "x11"   # строка 21
    ...
    from .app import LurkNotesApp        # строка 60, уже после установки env
```

`lurkn/app.py` импортирует `gi` и требует `Gtk`, `Gdk`, `GdkX11` (строки 29–35). Порядок соблюдён: `__main__` не импортирует `gi`/`.app` до установки переменной. Значит, **приложение само гарантирует X11-backend** независимо от окружения.

### Что делает `desktop-launch`

`desktop-launch` при наличии Wayland-сокета принудительно выставляет Wayland:

```bash
if [ "%FORCE_WAYLAND%" != "false" ] && [ "$wayland_available" = true ]; then
  export GDK_BACKEND="wayland"
  export CLUTTER_BACKEND="wayland"
  export QT_QPA_PLATFORM=wayland-egl
fi
```

([`gnome/launcher-specific`](https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/gnome/launcher-specific#L7-L12); в собранном снапе `%FORCE_WAYLAND%` = `true`.)

Но у `desktop-launch` есть штатный выход:

```bash
# Applications that don't support wayland natively may define DISABLE_WAYLAND
# (to any non-empty value) to skip that logic entirely.
wayland_available=false
if [[ -n "$XDG_RUNTIME_DIR" && -z "$DISABLE_WAYLAND" ]]; then
```

([`common/desktop-exports`](https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/common/desktop-exports#L265-L288).)

Поэтому в кандидате:

```yaml
    environment:
      DISABLE_WAYLAND: "1"
      GDK_BACKEND: "x11"
```

Комбинация устойчива: если env приложения выставляется до `command-chain`, `DISABLE_WAYLAND` отключает Wayland-ветку; если после — `GDK_BACKEND=x11` перекрывает выставленный `wayland`. В любом случае `__main__.main()` ещё раз ставит `x11` перед импортом GTK.

### Видимость X11-библиотек

См. §2: `libX11` и `libxcb` — из `mesa-2404` через `gpu-2404`; `libXcomposite`/`libXrender`/`libXcursor`/`libXrandr`/`libXi`/`libXinerama` — из `gnome-46-2404`. Обе директории попадают в `LD_LIBRARY_PATH` до запуска приложения (`gpu-2404-wrapper` + `desktop-launch`). `ctypes.CDLL("libX11.so.6")` в `src/lurkn/x11.py` находит библиотеку по этому пути — проверено на хосте с теми же каталогами.

**Не проверено в confinement:** реальные EWMH-трюки (`_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `STICKY`, `_NET_WM_DESKTOP`, `WM_HINTS.input`) под strict-снапом — это тикет 02. Здесь подтверждён только слой «библиотеки и backend доступны».

---

## 6. Кандидат `snapcraft.yaml`

```yaml
name: lurknotes
title: LurkNotes
base: core24
version: "0.1.0"

summary: Notes deck at the edge of the screen
description: |
  LurkNotes keeps a small deck of notes at the right edge of the screen.
  Hover the edge strip to fan out the notes, search them, and open one in a
  panel without leaving the current window. The app runs as an X11 client
  under XWayland, which is what lets the strip stay above other windows,
  outside the dock and on every workspace.

license: MIT
contact: aytpaev@gmail.com
website: https://github.com/hoter/lurknotes
source-code: https://github.com/hoter/lurknotes
issues: https://github.com/hoter/lurknotes/issues

grade: stable
confinement: strict
icon: packaging/lurknotes.svg

platforms:
  amd64:

apps:
  lurknotes:
    command: bin/lurknotes
    extensions: [gnome]
    desktop: usr/share/applications/lurknotes.desktop
    environment:
      # desktop-launch иначе выставляет GDK_BACKEND=wayland; приложение
      # дополнительно ставит x11 в __main__.main() до импорта GTK.
      DISABLE_WAYLAND: "1"
      GDK_BACKEND: "x11"

parts:
  lurknotes:
    plugin: python
    source: .

  desktop-assets:
    plugin: dump
    source: packaging
    organize:
      lurknotes.desktop: usr/share/applications/lurknotes.desktop
      lurknotes.svg: usr/share/icons/hicolor/scalable/apps/lurknotes.svg
```

### Чем проверен

1. **JSON-схема Snapcraft:** `jsonschema.validate(..., schema/snapcraft.json)` → `VALID` (schema из Snapcraft HEAD).
2. **`snapcraft expand-extensions`** (Snapcraft из исходников HEAD, `0.0.0.post1`) → команда отработала, конфиг развернулся; ключевые элементы приведены в §1. Никаких ошибок валидации/extension не было.
3. **Runtime-стек вне confinement:** `import lurkn.app` + `Gtk.init()` + `Gdk.Display` = `X11Display` + `ctypes.CDLL("libX11.so.6")` с библиотеками из `gnome-46-2404`/`mesa-2404` и Python 3.12.3 — успешно.

**Не проверено:** `snapcraft pack`, установка `--dangerous`, запуск в реальном strict-снапе, Store review.

### Замечания по кандидату

- `grade: stable` можно оставить и для первого релиза в `edge`; на время отладки удобнее `grade: devel` (не влияет на strict).
- `version: "0.1.0"` дублирует `pyproject.toml`; при желании заменить на `adopt-info`/`craftctl set version`, но для 0.1.0 это лишнее.
- `platforms: amd64` — только amd64, как в карте.
- `title`/`contact`/`website`/`source-code`/`issues` прошли схему; `contact` и `website` Snapcraft разворачивает в списки.
- Autostart в кандидат **не включён**: это тикет 04/08. Ключ `apps.<app>.autostart` существует (модель Snapcraft: desktop-файл кладётся в `$SNAP_USER_DATA/.config/autostart`, запуск идёт через command wrapper + аргументы из `Exec=`) — но поведение в strict-снапе и совместимость с GNOME session надо проверить отдельно.

---

## 7. Сборка: инструменты и команды

### Что нужно на машине сборки

| Инструмент | Версия/канал | Зачем |
|---|---|---|
| `snapcraft` | **9.2.1** (`latest/stable`, classic, 69.6 МБ) | сборка/упаковка |
| `lxd` | **6.10.0** (`latest/stable`, 140 МБ) | build-провайдер по умолчанию на Linux (Snapcraft 7+) |
| `multipass` | альтернатива | VM-провайдер; нужен на macOS/Windows; на Linux — если LXD не подходит |
| сеть | — | LXD-образ, `gnome-46-2404-sdk` 656 МБ, content-снапы, PyPI для `pip install .` |
| диск | ~5–10 ГБ | LXD storage + SDK + content + prime/сборка |

Официальная последовательность (Snapcraft docs, [Set up Snapcraft](https://github.com/canonical/snapcraft/blob/main/docs/how-to/set-up-snapcraft.rst)):

```bash
sudo snap install snapcraft --classic

sudo snap install lxd
sudo usermod -a -G lxd "$USER"     # затем выйти/войти в сессию
groups "$USER"                     # должен содержать lxd
sudo lxd init --auto

# при необходимости явно выбрать провайдера
snap set snapcraft provider=lxd
```

Сборка и локальная проверка:

```bash
snapcraft expand-extensions        # посмотреть, что добавил gnome
snapcraft pack                     # соберёт lurknotes_0.1.0_amd64.snap
sudo snap install --dangerous ./lurknotes_0.1.0_amd64.snap
snap run lurknotes
snap connections lurknotes         # gpu-2404, gnome-46-2404, x11, wayland...
```

### Multipass

```bash
sudo snap install multipass
snap set snapcraft provider=multipass
```

VM требует вложенной виртуализации; на десктопе обычно работает, но тяжелее LXD. Ресурсы VM при необходимости задаются через `SNAPCRAFT_BUILD_ENVIRONMENT_CPU/MEMORY`; на этой машине (22 CPU/15 ГБ) дефолтов достаточно.

### Destructive mode

```bash
snapcraft pack --destructive-mode
```

- Собирает прямо на хосте, без контейнера; **не рекомендуется**.
- Хост должен совпадать с base: для core24 — Ubuntu 24.04 (эта машина подходит).
- Для core22+ нужны root-права: Snapcraft ставит apt-пакеты и снапы в хостовую систему
  ([Build environment options](https://github.com/canonical/snapcraft/blob/main/docs/reference/build-environment-options.rst#destructive-mode)).
- На этой машине `sudo` просит пароль, поэтому даже destructive mode без владельца не запустить.

### Статус на этой машине

- `snapcraft` — нет; `lxd` — нет; `sudo -n true` → требует пароль.
- Поэтому **сборка не выполнялась**. Для проверки extension я поставил Snapcraft из исходников в `/tmp/opencode/scvenv` (не в систему) и прогнал `expand-extensions`; это не поддерживаемый способ сборки, только валидация конфига.
- Первый реальный билд должен сделать владелец (интерактивный sudo) либо одноразовая Ubuntu 24.04 VM/CI. Карта уже вынесла CI за скобки.

---

## 8. Риски и открытые вопросы

1. **Версия GTK в снапе отличается от проверенной.** Хост: GTK 4.14.5 / PyGObject 3.48.2. `gnome-46-2404` rev 177: GTK **4.20.4** / PyGObject **3.56.2**; установленный rev 168: GTK 4.18.6. Приложение проверялось на 4.14.5. Импорт и `Gtk.init()` на 4.20.4 прошли, но полный UI (CSS, `Gtk.Window`/X11 hints, жесты) не прогонялся. Content-снап обновляется независимо от релиза приложения — поведение может измениться без нового снапа LurkNotes.
2. **X11-стек зависит от `mesa-2404`.** `libX11.so.6` есть только в `mesa-2404` (через `gpu-2404`). Если content-подключение не состоится, GTK X11-backend и `ctypes.CDLL("libX11.so.6")` упадут. Автоконнект content-плагинов с `default-provider` обычно работает, но это надо проверить на чистой установке (`snap connections`).
3. **Strict confinement и EWMH** — тикет 02; здесь не проверялись `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `STICKY`, `_NET_WM_DESKTOP`, `WM_HINTS.input`, позиционирование у края.
4. **D-Bus single instance** (`dev.lurknotes.LurkNotes`) под strict-снапом — тикет 03. Если snapd не даст владеть именем, второй экземпляр не будет передавать argv первому.
5. **Данные и autostart** — тикеты 03/04/08. `HOME`/`XDG_*` в strict-снапе указывают в `$SNAP_USER_DATA`; `--install-autostart` пишет desktop-файл в приватный `$XDG_CONFIG_HOME` снапа, а не в хостовый `~/.config/autostart`. Поэтому для snap, вероятно, нужен `apps.<app>.autostart`; как именно GNOME 46 увидит этот файл — открытый вопрос тикета 04/08.
6. **Иконка/листинг** — тикет 07. Текущий SVG 128×128; Store может требовать PNG 256×256; `Name=Lurk Notes` в desktop-файле расходится с листинговым `LurkNotes`.
7. **Сборка не воспроизведена.** Валидны схема и expansion, но не факт, что `pip install .` и упаковка пройдут в LXD-контейнере; особенно стоит проверить build isolation (`setuptools>=68` с PyPI) и shebang `bin/lurknotes` в реальном снапе.
8. **`expand-extensions` гонялся на Snapcraft HEAD (post-9.2.1),** а не на точной 9.2.1. Поведение extension/python plugin в 9.2.1 с большой вероятностью то же (изменений в этих файлах между 9.2.1 и HEAD не проверял), но это не побайтовая проверка.
9. **Порядок `environment` vs `command-chain`** в snapd не проверялся по исходникам; комбинация `DISABLE_WAYLAND` + `GDK_BACKEND` + код приложения устойчива при любом порядке, но если хочется абсолютной гарантии — добавить wrapper-скрипт после `command-chain` (не требуется для текущего кода).
10. **`libX11` из mesa — хрупкая зависимость по смыслу.** Если нужна независимость от GPU-снапа, можно stage-ить X11-библиотеки и явно добавить `$SNAP/usr/lib/$CRAFT_ARCH_TRIPLET` в `LD_LIBRARY_PATH`, но это противоречит модели extension и требует отдельного теста на конфликт версий; сейчас не рекомендую.

---

## 9. Источники

### Snapcraft

- GNOME extension (код): https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gnome.py
- GPU extension (код): https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/extensions/gpu_extension.py
- GNOME extension (docs): https://github.com/canonical/snapcraft/blob/main/docs/reference/extensions/gnome-extension.rst
- Python plugin / base interpreter: https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/plugins/python_common.py#L36-L90 и https://github.com/canonical/snapcraft/blob/main/docs/reference/plugins/_python_common.rst
- Desktop-файл и иконка (код): https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/desktop_file.py#L71-L100, https://github.com/canonical/snapcraft/blob/cdab9e661583d07cf2aa1a573f7d55db4befccce/snapcraft/parts/setup_assets.py#L279-L329
- Desktop/icon (docs): https://github.com/canonical/snapcraft/blob/main/docs/how-to/crafting/configure-package-information.rst
- Build providers: https://github.com/canonical/snapcraft/blob/main/docs/how-to/set-up-snapcraft.rst, https://github.com/canonical/snapcraft/blob/main/docs/how-to/select-a-build-provider.rst
- Destructive mode: https://github.com/canonical/snapcraft/blob/main/docs/reference/build-environment-options.rst#destructive-mode
- Модель проекта (icon, autostart, platforms): https://github.com/canonical/snapcraft/blob/main/snapcraft/models/project.py
- JSON-схема: https://github.com/canonical/snapcraft/blob/main/schema/snapcraft.json

### craft-parts / desktop integration

- Python plugin venv: https://github.com/canonical/craft-parts/blob/8de841e9b129060ced0693b746855ce0c131f5e5/craft_parts/plugins/base.py
- `desktop-launch`: https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/common/desktop-exports#L265-L288 (DISABLE_WAYLAND, LD_LIBRARY_PATH), https://github.com/canonical/snapcraft-desktop-integration/blob/fbfab52ffc2238478c5b952087b455920b1648b5/gnome/launcher-specific#L7-L26 (GDK_BACKEND=wayland, PYTHONPATH)

### GNOME SDK / content snap

- `ubuntu/gnome-sdk`, ветка gnome-46-2404: https://github.com/ubuntu/gnome-sdk/blob/gnome-46-2404/snap/snapcraft.yaml (stage-packages `python3-gi`, `python3.12-minimal`, `libx11-6`; `WITH_PYTHON=3.12`)
- Store-метаданные: `snap info gnome-46-2404` (rev 177, 646 МБ), `snap info gnome-46-2404-sdk` (rev 206, 656 МБ), `snap info mesa-2404` (rev 1839, 422 МБ), `snap info core24` (rev 2124)

### Локальные проверки

```bash
snap --version                                  # 2.77.1+ubuntu24.04
snap info core24 gnome-46-2404 gnome-46-2404-sdk mesa-2404

snap download core24 --channel=stable
snap download gnome-46-2404 --channel=stable
snap download mesa-2404 --channel=stable
unsquashfs -d core24 core24_2124.snap
unsquashfs -d gnome46 gnome-46-2404_177.snap

# base: python есть, gi/typelib нет
core24/usr/bin/python3.12 --version            # 3.12.3
find core24 -name '*.typelib' | wc -l          # 0

# content snap: GTK 4.20.4, PyGObject 3.56.2, typelibs
strings gnome46/usr/lib/x86_64-linux-gnu/libgtk-4.so.1.2000.4 | grep '^4\.20\.'
ls gnome46/usr/lib/python3/dist-packages/gi/_gi.cpython-312-x86_64-linux-gnu.so
ls gnome46/usr/lib/x86_64-linux-gnu/girepository-1.0/Gtk-4.0.typelib

# libX11: нет в base и gnome, есть в mesa
find core24 gnome46 -name 'libX11.so*'        # пусто
ls /snap/mesa-2404/current/usr/lib/x86_64-linux-gnu/libX11.so.6

# runtime-проверка вне confinement
G=$PWD/gnome46
LD_LIBRARY_PATH="$G/usr/lib/x86_64-linux-gnu:/snap/mesa-2404/current/usr/lib/x86_64-linux-gnu" \
PYTHONPATH="$G/usr/lib/python3.12:$G/usr/lib/python3/dist-packages" \
GI_TYPELIB_PATH="$G/usr/lib/x86_64-linux-gnu/girepository-1.0" \
GDK_BACKEND=x11 DISPLAY=:0 python3 -c '
import gi; gi.require_version("Gtk","4.0")
from gi.repository import Gtk, Gdk
Gtk.init(); print(Gtk.get_minor_version(), type(Gdk.Display.get_default()).__name__)
import ctypes; ctypes.CDLL("libX11.so.6"); print("libX11 ok")'
# → 20 X11Display / libX11 ok

# конфиг
python3 - <<'EOF'
import json, yaml, jsonschema
jsonschema.validate(yaml.safe_load(open("snapcraft.yaml")),
                    json.load(open("schema/snapcraft.json")))
print("VALID")
EOF

# expansion (Snapcraft из исходников в /tmp venv)
snapcraft expand-extensions
```

**Ограничение:** всё, что связано с `snapcraft pack`, установкой снапа и поведением в strict-confinement, осталось непроверенным: на машине нет `snapcraft`/LXD, а `sudo` требует пароль.
