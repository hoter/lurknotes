# Research: снап-рецепт для PyGObject/GTK4

Type: research
Status: open
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
