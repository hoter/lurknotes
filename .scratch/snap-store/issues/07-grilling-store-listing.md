# Grilling: листинг в Snap Store

Type: grilling
Status: resolved
Blocked by:

## Question

Зафиксировать содержимое страницы Store: название, summary, description,
категория, keywords, скриншоты, homepage, контакт, лицензия.

Рекомендации для обсуждения:

- title `LurkNotes`, snap name `lurknotes`;
- summary: «Notes deck at the edge of the screen for Ubuntu / GNOME»;
- description: 3–5 абзацев о колоде, peek, поиске, локальном JSON,
  X11/XWayland-требовании;
- category `utilities` (слаг Store; поля keywords в форме нет);
- скриншоты из `docs/screenshots` (fan, peek, search, note, drag, empty);
- homepage `https://github.com/hoter/lurknotes`;
- contact `aytpaev@gmail.com`, license MIT;
- язык листинга — английский.

Ответ — утверждённый текст и список ассетов; сами ассеты готовятся после карты.

## Answer

Согласовано с владельцем. Итоговый листинг:

- **Title:** `LurkNotes`; **snap name:** `lurknotes`.
- **Summary:** `Notes deck at the edge of the screen for Ubuntu / GNOME`.
- **Category:** `utilities` (слаг Store); поля keywords в форме нет.
- **Homepage:** <https://github.com/hoter/lurknotes>.
- **Contact:** `aytpaev@gmail.com`; **license:** MIT (файл `LICENSE` добавить
  в execution-заходе); **language:** English.
- **Скриншоты:** для Store сделать 16:9-карточки 1600×900 (fan, peek, search,
  note, drag, empty) на тёмном фоне с подписями; портретные 390×928 остаются
  в README. Иконка — `packaging/lurknotes.svg`, баннер опционален.
- **X11:** упоминаем требование X11/XWayland и отсутствие native Wayland mode.
- **Автозапуск:** в описании пока не упоминаем — механизм решается в 09.

### Description

```text
LurkNotes keeps your notes on a narrow strip at the right edge of the screen —
out of the way until you need them.

Hover the strip to unfold a fan of notes. Hover a tab to peek at its first
lines, click to open the editor. Drag tabs to reorder the deck; edits autosave
after 400 ms. Search filters the deck as you type, and deleting a note leaves a
10-second undo.

Everything is stored locally in a single JSON file, with a backup and recovery
for a damaged file. No account, no network, no telemetry.

LurkNotes is a GTK4 application for Ubuntu 24.04 / GNOME 46. It runs as an X11
client under XWayland, which is what lets the deck stay above other windows,
outside the dock and on every workspace. There is no native Wayland mode; an
X11/XWayland session is required.
```
