# Публикация LurkNotes в Snap Store — чек-лист

Тикеты: `.scratch/snap-store/` (06 — аккаунт, 11 — релиз).

## Уже сделано в репозитории
- `snapcraft.yaml`: `core24`, `strict`, `[gnome]`, amd64, `grade: stable`,
  `adopt-info` из AppStream, `LURKNOTES_APP_ID=io.github.hoter.LurkNotes`,
  `GDK_BACKEND=x11`. Собирается через Multipass:
  `snapcraft pack` → `lurknotes_0.1.0_amd64.snap`.
- Части сборки:
  - `slots.dbus-lurknotes` — session `dbus`, имя `io.github.hoter.LurkNotes`;
    без него `Gtk.Application` падает в strict-снапе с
    `AccessDenied: ... not allowed to own the service`. При публикации в Store
    слот проходит ручное ревью (05).
  - `lurknotes` — `plugin: nil`, код копируется в `$SNAP/site-packages/lurkn`
    в `override-build`; AppStream-файл зеркалируется в src/build/install,
    иначе `parse-info` молча не находит его.
  - `desktop-assets` — `plugin: dump`, но весь install пишется в
    `override-build` (Name/Icon/Exec под snap-id); `organize` не используется.
- `packaging/io.github.hoter.LurkNotes.metainfo.xml` — проходит
  `appstreamcli validate`.
- `packaging/dev.lurknotes.LurkNotes.desktop` — deb-версия, проходит
  `desktop-file-validate`; snap переписывает её при сборке.
- `LICENSE` (MIT), `.gitignore` для `parts/ stage/ prime/ *.snap`.
- `lurknotes --install-autostart` пишет файл под текущим id (snap ставит свой).

## Шаги

1. **Аккаунт.** https://snapcraft.io → Ubuntu One; Developer Programme
   Agreement; 2FA.
2. **Логин.** `snapcraft login`, `snapcraft whoami`, `snapcraft names`.
3. **Регистрация имени.** `snapcraft register lurknotes` — **сделано**
   (2026-11-04).
4. **Build provider.** Используется Multipass:
   `sudo snap install multipass && snap set snapcraft provider=multipass`
   (нет `sudo`/VPN-сетей — LXD на этой машине не работает).
5. **Сборка.** `snapcraft pack` → `lurknotes_0.1.0_amd64.snap`.
   После изменения `snapcraft.yaml` (scriptlet/parts) — `snapcraft clean`,
   иначе старые `install/` каталоги остаются с hardlink-конфликтами.
6. **Локальная проверка (сделана 2026-11-04).**
   `sudo snap install --dangerous ./lurknotes_0.1.0_amd64.snap`, ревизия x2,
   затем `snap run lurknotes`. Результат:
   - `snap connections lurknotes`: подключены `gnome-46-2404`, `gpu-2404`,
     `gtk-3-themes`, `icon-themes`, `sound-themes`, `desktop`,
     `desktop-legacy`, `gsettings`, `opengl`, `wayland`, `x11`;
     `dbus` → `lurknotes:dbus-lurknotes` (идёт слотом).
   - Заметки пишутся в `~/snap/lurknotes/current/.local/share/lurknotes/`
     (`notes.json`, `notes.bak.json`, `onboarded`).
   - Одиночный экземпляр (`snap run lurknotes new`), автозапуск через
     `--install-autostart` и X11-поведение (above/вне дока/все рабочие столы)
     проверены и работают.
   - В stderr три `Gtk-WARNING … GtkGizmo … min width -6` от GTK 4.20.4
     из `gnome-46-2404` (на хосте GTK 4.14.5); не fatal, интерфейс корректен.
7. **Edge.** `snapcraft upload --release=edge ./lurknotes_0.1.0_amd64.snap`;
   дождаться ручного ревью (Store → Listing → опубликовать листинг).
8. **Stable.** После проверки: `snapcraft promote lurknotes --from-channel edge --to-channel stable`
   (или `snapcraft release lurknotes <rev> stable`).

## Локальные ограничения этой машины (2026-11-04)

- `snapcraft` 9.2.1 (classic), сборка через Multipass 5.x/VM Ubuntu 24.04.
- LXD 5.21 установлен, но контейнер не имеет выхода наружу:
  `lxd init --auto` упирается в подсети docker/VPN (лечится
  `scripts/setup_lxd.sh`), а сеть контейнера после этого не форвардит
  (конфликт с Docker 29 на хосте) — поэтому Multipass.
- `remote-build` падает на 504 (git-сервис Launchpad), креды
  `~/.local/share/snapcraft/launchpad-credentials` сохранены; по причинам
  безопасности токен, попавший в переписку, стоит перевыпустить.
