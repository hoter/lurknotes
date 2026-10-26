# LurkNotes для Ubuntu — карта

**Статус:** маршрут пройден, спека собрана — [spec.md](spec.md). Реализация: [plan.md](plan.md) (M0–M9, спайки A–C).

## Destination

Спека и набор решений для «колоды заметок у края экрана» под Ubuntu 24.04 / GNOME 46 / Wayland, достаточные, чтобы сесть и написать MVP без новых решений. Раздача в Flathub и возможный переход на Rust — за краем этой карты.

## Notes

- Домен: локальное десктоп-приложение для заметок. Референс — Peeky Notes (Windows, peekynotes.in).
- Окружение: Ubuntu 24.04.5, Wayland, GNOME 46; GTK4 4.14, libadwaita 1.5, PyGObject 3.48 установлены; Rust и `pkg-config` отсутствуют; sudo с паролем.
- **Платформа:** Mutter 46 не реализует `zwlr_layer_shell_v1`, пакет `libgtk-layer-shell0` в noble собран под GTK3. «У края поверх окон» обычным Wayland-приложением недостижимо — выбран XWayland (14).
- Трекер: локальный markdown, `.scratch/edge-notes/` (слаг усилия исторический; продукт — LurkNotes). Статусы: `open`, `claimed`, `resolved`, `superseded`.
- Имя: **LurkNotes** (зафиксировано в 06). Бинарник `lurknotes`, application id `dev.lurknotes.LurkNotes`, данные в `~/.local/share/lurknotes/`.
- Тикеты: HITL — `grilling` + `domain-modeling`; research — `research`; prototype — `prototype`.
- Базовый стек: GTK4 + Python (PyGObject) под XWayland (`GDK_BACKEND=x11`); Rust — только при выходе в продукт. Запасной путь — GNOME Shell extension (GJS), если прототип провалит z-order или док.
- UI на английском, все строки в одном модуле.
- Решения 08–13 приняты в сессии чартинга (живой диалог с человеком) и лежат как baseline карты.

## Decisions so far

- [Layer-shell на GNOME 46](issues/01-research-layer-shell.md): протокола нет в Mutter 46, пакет в noble — GTK3; «у края поверх окон» обычным Wayland-приложением недостижимо.
- [Хоткеи и единый экземпляр](issues/02-research-global-shortcut.md): портала `GlobalShortcuts` нет; ручные `Ctrl+Alt+N` / `Ctrl+Alt+A` на CLI, единый экземпляр через `Gtk.Application` + `HANDLES_COMMAND_LINE`, фокус на Wayland не гарантирован.
- [Модель взаимодействия колоды](issues/03-deck-interaction.md): три состояния (strip → fan → panel), два уровня наведения, одна панель, новая заметка сверху, колесо прокручивает веер, один порядок для колоды и All Notes.
- [Что входит в первую версию](issues/08-decision-scope.md): ядро колоды + drag-порядок + undo-удаление; архив, импорт/экспорт, portable, цвета — потом. Автостарт пересмотрен в 06: входит в v1.
- [Стек](issues/09-decision-stack.md): GTK4 + Python; Rust — условие выхода в продукт; Tauri и Electron отклонены.
- [Хранение](issues/10-decision-storage.md): один JSON в `~/.local/share/lurknotes/notes.json`, атомарная запись + бэкап.
- [Редактор и заголовок](issues/12-decision-editor.md): плоский текст + markdown-шорткаты; заголовок = первая строка.
- [Хоткей и язык](issues/13-decision-integration.md): ручная привязка в GNOME Settings, английский UI, строки в одном модуле.
- [Механизм окна у края](issues/14-mechanism.md): XWayland + EWMH (`ABOVE`, `SKIP_TASKBAR`, `STICKY`); layer-shell отменён.
- [Прототип колоды](issues/05-prototype-deck.md): XWayland-подход подтверждён — панель поверх окон, вне дока и Alt+Tab; peek и drag полезны; фокус по наведению не забираем; нужны явные кнопки сворачивания.
- [Жизненный цикл заметки](issues/04-note-lifecycle.md): порядок = индекс массива; пустая заметка удаляется при закрытии; undo 10 с только в памяти; заголовок = первая строка; поиск подстрокой; All Notes по ручному порядку; атомарная запись + бэкап.
- [Единый экземпляр](issues/06-single-instance.md): CLI `lurknotes new|all`; холодный старт доводит действие до конца; автостарт в v1; при отказе в фокусе — подсказка «Click to type»; имя LurkNotes, данные в `~/.local/share/lurknotes/`.
- [Собрать спеку](issues/07-spec.md): [spec.md](spec.md) — домен, данные, интерфейс, интеграция, критерии готовности MVP; один монитор, тёмная тема, бюджет 1.5 с / 120 МБ.

## Not yet specified

Нет — всё, что было в тумане, либо решено, либо явно вынесено за край карты.

## Out of scope

- Лицензия, триал, оплата (модель Peeky) — отдельное усилие.
- Windows и macOS версии.
- Синхронизация, аккаунты, телеметрия — противоречит обещанию «заметки не покидают машину».
- X11-сессия как целевая платформа: приложение идёт через XWayland внутри Wayland-сессии.
- Русский UI в v1.
- Упаковка и распространение (flatpak/deb, обновления) — за краем карты.
- Визуальная полировка UI (анимации, типографика, светлая тема) — после MVP, не часть спеки.
- Цвета заметок — после MVP: ядру хватает одного акцента.
- Мультимонитор: v1 живёт на основном мониторе; поведение при отключении не определено.
- Поддержка не-GNOME композиторов (Sway, KDE) — отдельное усилие, двойной backend не делаем.
- Переход на Rust — если MVP не уложится в бюджет 1.5 с старта и 120 МБ памяти.
- Архив, импорт/экспорт, portable-режим — отложенный паритет.
