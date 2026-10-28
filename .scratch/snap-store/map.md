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
- Листинг: `LurkNotes`, категория `Utility`, homepage — GitHub-репозиторий,
  контакт `aytpaev@gmail.com`.
- Human-only шаги (аккаунт, Publisher Agreement, регистрация имени, финальный
  Release) — за владельцем; в карте они оформлены task-тикетом с чек-листом.
- Факты окружения на 2026-10-28: snapd 2.77.1, `snapcraft` не установлен,
  имя `lurknotes` в Store свободно, файла LICENSE нет, архитектура amd64.
- Skills: решения — `grilling` + `domain-modeling`; факты — `research`.
- После закрытия карты execution включает: MIT LICENSE, `snapcraft.yaml`,
  сборку, тест на чистой Ubuntu 24.04, тексты листинга, отправку и `stable`.

## Decisions so far

- [Research: автозапуск снапа](issues/04-research-autostart.md): `apps.<name>.autostart` — только basename; snapd ищет файл в `$SNAP_USER_DATA/.config/autostart`, который приложение пишет само при первом запуске; `--autostart` передаётся только если явно указан в `Exec=`.

## Not yet specified

- Если `strict` + X11 не воспроизведёт поведение «у края поверх окон» —
  решить, просить ли classic (отдельное ревью) или менять механизм окна.
- Где собирать snap (локальный LXD/Multipass или одноразовая VM) — станет ясно
  после исследования требований `snapcraft`.
- Ожидания по данным существующих пользователей GitHub/deb: миграция или
  отдельное хранилище snap (зависит от 03 и 10).
- Нужен ли snap-сборке отдельный application id/D-Bus name, чтобы не
  конфликтовать с deb/pipx-версией (03).
- Детали скриншотов и текста листинга (07).
- Судьба `--install-autostart` для не-snap установок (08).
- Политика версии/ревизий при обновлениях в Store (11).
- Поведение при удалении snap: сохраняются ли заметки, нужен ли экспорт (12).

## Out of scope

- Flatpak и публикация в Flathub.
- deb в архиве Ubuntu, PPA, AppImage.
- CI-автоматизация сборки и релиза snap в этом заходе.
- Wayland-нативный край и GNOME Shell extension.
- arm64 и Ubuntu младше 24.04.
- Новые продуктовые фичи, кроме минимальной адаптации автозапуска/онбординга.
- Платная модель, триал, синхронизация.
