# Grilling: приёмочный тест snap

Type: grilling
Status: open
Blocked by: 08, 09, 10

## Question

Выбрать матрицу проверки на чистой Ubuntu 24.04 и критерии прохождения:

- Wayland-сессия (XWayland) и Xorg-сессия;
- установка `snap install` из edge/stable, первый запуск, автозапуск;
- поведение у края: ABOVE, вне дока/Alt+Tab, фокус, клики, hover;
- данные: создание, сохранение, перезапуск, `snap refresh`, `snap remove`;
- хоткей `Ctrl+Alt+N`, `--version`, `--help`;
- отсутствие доступа к лишним путям, отсутствие сетевых запросов;
- что фиксируем как known limitation (X11/XWayland, fullscreen).

Ответ — чек-лист с командами и pass/fail, пригодный для повторного прогона.
