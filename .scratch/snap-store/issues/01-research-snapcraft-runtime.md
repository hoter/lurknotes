# Research: снап-рецепт для PyGObject/GTK4

Type: research
Status: resolved
Blocked by:

Research branch: `research/snapcraft-runtime` (findings: `.scratch/snap-store/research/01-snapcraft-runtime.md`)

## Question

Как собрать LurkNotes (Python 3.12, PyGObject, GTK 4.14) под `core24` со стеком
GNOME 46 в strict-confinement снапе?

Нужны факты из первоисточников (Snapcraft docs, Canonical/snapcraft,
ubuntu/gnome-sdk, snapd):

- какой base/extension использовать (`core24` + `gnome`?) и что именно даёт
  extension, а что надо ставить через `stage-packages`;
- нужен ли `python` plugin или достаточно `dump`/`stage-packages` с
  `python3-gi`, `gir1.2-gtk-4.0`, `libx11-6`; где брать `gi` для Python 3.12;
- как объявить команду `lurknotes`, desktop-файл и иконку;
- как приложение должно выставлять `GDK_BACKEND=x11` и видеть X11-библиотеки;
- минимальный рабочий `snapcraft.yaml` (кандидат) и команды сборки;
- какие инструменты нужны на машине сборки (LXD/Multipass/destructive mode).

Ответ — отчёт с ссылками на первоисточники и готовым кандидатом конфига.

## Answer

Resolved by research on branch `research/snapcraft-runtime`; full report:
<https://github.com/hoter/lurknotes/blob/research/snapcraft-runtime/.scratch/snap-store/research/01-snapcraft-runtime.md>

- `base: core24` + `extensions: [gnome]` is sufficient. The extension pulls
  `gnome-46-2404` (GTK/PyGObject/typelibs), `mesa-2404` (GPU and X11 libs),
  `gtk-common-themes`, `desktop-launch` and the build SDK; no GTK/PyGObject
  `stage-packages` are needed.
- core24 ships Python 3.12.3 but no `gi`; `gnome-46-2404` rev 177 provides
  GTK **4.20.4**, PyGObject **3.56.2** and `Gtk-4.0`/`GdkX11-4.0` typelibs.
  This is newer than the host GTK 4.14.5 the app is tested against.
- **libX11 is not in core24 or gnome-46-2404.** It comes from `mesa-2404` via the
  `gpu-2404` content plug, whose wrapper adds its lib dir to `LD_LIBRARY_PATH`;
  X11 support therefore depends on `gpu-2404` being connected.
- The `python` plugin is optional: the base interpreter works, and `gi` comes via
  the content snap's `PYTHONPATH`. A `dump` + wrapper is a viable no-PyPI path.
- `command: bin/lurknotes`; `desktop:` must point inside prime, so a small `dump`
  part stages `packaging/lurknotes.desktop`; top-level `icon:` lands as
  `meta/gui/icon.svg` and Snapcraft rewrites `Icon=`.
- Set `DISABLE_WAYLAND=1` + `GDK_BACKEND=x11` in the snap environment: the
  `desktop-launch` wrapper otherwise forces Wayland (the app also sets it in
  `__main__` before importing GTK).
- The candidate config passes the Snapcraft JSON schema and
  `snapcraft expand-extensions`; a real `snapcraft pack`, strict install and
  Store review were not possible here (no snapcraft/LXD, sudo needs a password).
- Build tooling: Snapcraft 9.x + LXD 6.x, Multipass, or destructive mode/VM.
  GTK 4.20 vs 4.14 and the independently updating content snap are the main
  compatibility risks to verify in the test plan (12).
