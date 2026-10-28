# LurkNotes в Snap Store — карта

**Статус:** чартинг завершён, маршрут открыт; research-тикеты запущены.

## Destination

LurkNotes 0.1.0 опубликован в Snap Store в канале `stable`: установка
`sudo snap install lurknotes`, полный листинг, strict confinement, amd64 на
`core24`, поведение приложения как в текущем X11/XWayland-релизе, лицензия MIT.

## Notes

- Домен и продукт — [LurkNotes](../../README.md), [спека](../edge-notes/spec.md).
  Это усилие только про упаковку и публикацию, без изменения продукта.
- Трекер локальный: `.scratch/snap-store/`, статусы `open` / `claimed` /
  `resolved` / `superseded`; блокировки — `Blocked by:` в тикете.
- Решения чартинга: только Snap Store (не архив Ubuntu); критерий готовности —
  `stable` + полный листинг, сначала `edge`; публикуем 0.1.0 как есть с
  требованием X11/XWayland; лицензия MIT; amd64 + `core24`; карта даёт решения
  и маршрут, реализация — отдельным заходом после её закрытия.
- Confinement `strict`; автозапуск по умолчанию: `snapcraft.yaml` объявляет только
  basename, а файл в `$SNAP_USER_DATA/.config/autostart` приложение пишет само
  при первом запуске (04); `--install-autostart` для snap-сборки убираем.
- Листинг: `LurkNotes`, категория `utilities` (слаг Store; поля keywords нет),
  homepage — GitHub-репозиторий, контакт `aytpaev@gmail.com`.
- Human-only шаги (аккаунт, Developer Programme Agreement, регистрация имени
  с ручным ревью, финальный Release) — за владельцем; task-тикет с чек-листом.
- Факты окружения на 2026-10-28: snapd 2.77.1, `snapcraft` не установлен,
  имя `lurknotes` в Store свободно, файла LICENSE нет, архитектура amd64.
- Skills: решения — `grilling` + `domain-modeling`; факты — `research`.
- После закрытия карты execution включает: MIT LICENSE, `snapcraft.yaml`,
  сборку, тест на чистой Ubuntu 24.04, тексты листинга, отправку и `stable`.

## Decisions so far

- [Research: автозапуск снапа](issues/04-research-autostart.md): `apps.<name>.autostart` — только basename; snapd ищет файл в `$SNAP_USER_DATA/.config/autostart`, который приложение пишет само при первом запуске; `--autostart` передаётся только если явно указан в `Exec=`.
- [Research: снап-рецепт для PyGObject/GTK4](issues/01-research-snapcraft-runtime.md): `core24` + `[gnome]` даёт GTK 4.20/PyGObject; libX11 приходит из `mesa-2404` через `gpu-2404`; `python` plugin опционален; нужен `DISABLE_WAYLAND=1`/`GDK_BACKEND=x11`.
- [Research: данные и единый экземпляр в снапе](issues/03-research-data-and-instance.md): snap видит только `$SNAP_USER_DATA`; старый `~/.local/share` недоступен без `personal-files` (не берём); нужен собственный app id и `dbus` slot, данные — в `SNAP_USER_DATA`, миграция вручную.
- [Research: публикация и ревью в Snap Store](issues/05-research-store-review.md): регистрация имени — ручное ревью (Developer Programme Agreement); категория `utilities`, keywords в Store нет; `x11`/`desktop`/`autostart` ревью не триггерят, `dbus` slot — триггерит; ревизии неизменяемы, откат — переrelease.

- [Research: автозапуск снапа](issues/04-research-autostart.md): `apps.<name>.autostart` — только basename; snapd ищет файл в `$SNAP_USER_DATA/.config/autostart`, который приложение пишет само при первом запуске; `--autostart` передаётся только если явно указан в `Exec=`.
- [Research: снап-рецепт для PyGObject/GTK4](issues/01-research-snapcraft-runtime.md): `core24` + `[gnome]` даёт GTK 4.20/PyGObject; libX11 приходит из `mesa-2404` через `gpu-2404`; `python` plugin опционален; нужен `DISABLE_WAYLAND=1`/`GDK_BACKEND=x11`.
- [Research: данные и единый экземпляр в снапе](issues/03-research-data-and-instance.md): snap видит только `$SNAP_USER_DATA`; старый `~/.local/share` недоступен без `personal-files` (не берём); нужен собственный app id и `dbus` slot, данные — в `SNAP_USER_DATA`, миграция вручную.

- [Research: автозапуск снапа](issues/04-research-autostart.md): `apps.<name>.autostart` — только basename; snapd ищет файл в `$SNAP_USER_DATA/.config/autostart`, который приложение пишет само при первом запуске; `--autostart` передаётся только если явно указан в `Exec=`.
- [Research: снап-рецепт для PyGObject/GTK4](issues/01-research-snapcraft-runtime.md): `core24` + `[gnome]` даёт GTK 4.20/PyGObject; libX11 приходит из `mesa-2404` через `gpu-2404`; `python` plugin опционален; нужен `DISABLE_WAYLAND=1`/`GDK_BACKEND=x11`.

- [Research: автозапуск снапа](issues/04-research-autostart.md): `apps.<name>.autostart` — только basename; snapd ищет файл в `$SNAP_USER_DATA/.config/autostart`, который приложение пишет само при первом запуске; `--autostart` передаётся только если явно указан в `Exec=`.

## Not yet specified

- Если `strict` + X11 не воспроизведёт поведение «у края поверх окон» —
  решить, просить ли classic (отдельное ревью) или менять механизм окна.
- Окружение сборки/тестов: LXD (не-root после добавления в группу `lxd`, что
  эквивалентно root), Multipass/remote-build или destructive mode под root;
  выбор — в 12.
- Политика данных и миграция существующих пользователей: 03 дал факты
  (snap видит только `$SNAP_USER_DATA`, старый `~/.local/share` недоступен без
  `personal-files`); решение — в 10.
- Snap нужен собственный application id и `dbus` slot; именованный `dbus`
  slot — ручное ревью Store. Какой id (`dev.lurknotes.*` /
  `io.github.hoter.*`) и как мигрировать — в 10.
- Детали скриншотов и текста листинга (07).
- Судьба `--install-autostart` для не-snap установок (08).
- Политика версии/ревизий при обновлениях в Store (11).
- Удаление snap: данные удаляются, но snapd оставляет snapshot ~31 день;
  проверить и решить про экспорт — 12.

## Out of scope

- Flatpak и публикация в Flathub.
- deb в архиве Ubuntu, PPA, AppImage.
- CI-автоматизация сборки и релиза snap в этом заходе.
- Wayland-нативный край и GNOME Shell extension.
- arm64 и Ubuntu младше 24.04.
- Новые продуктовые фичи, кроме минимальной адаптации автозапуска/онбординга.
- Платная модель, триал, синхронизация.
