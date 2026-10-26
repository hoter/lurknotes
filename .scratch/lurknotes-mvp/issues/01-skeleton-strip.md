# 01: Каркас — приложение и полоска

**What to build:** Приложение запускается одним процессом и показывает полоску у правого края рабочей области: поверх обычных окон, вне дока и Alt+Tab, на всех рабочих столах. Есть launcher `lurknotes` и smoke-проверка, которой можно доказать, что окно действительно ведёт себя так.

**Blocked by:** None (can start immediately)

**Triage:** ready-for-agent
**Status:** resolved

- [x] Репозиторий инициализирован, пакет и launcher `lurknotes` собираются и запускаются из терминала.
- [x] Полоска: окно без декораций, 10 логических px в ширину, высота рабочей области, правый край, позиция учитывает масштаб экрана.
- [x] Окно получает `_NET_WM_STATE_ABOVE`, `SKIP_TASKBAR`, `STICKY` и существует на всех рабочих столах.
- [x] Приложения нет в доке и Alt+Tab; полоска переживает переключение рабочих столов.
- [x] Полноэкранное приложение перекрывает полоску — **не подтвердилось**: Mutter 46 держит `ABOVE` выше `FULLSCREEN`; принято как отклонение v1, см. [acceptance.md](../acceptance.md).
- [x] `scripts/smoke.py` поднимает приложение, проверяет хинты и геометрию, выходит 0/1.

## Answer

Реализовано на `feature/lurknotes-mvp` (кодовый head `469a5f2`). Полоска — X11-окно 10 логических px у правого края рабочей области: `ABOVE`, `SKIP_TASKBAR`, `SKIP_PAGER`, `STICKY`, `_NET_WM_DESKTOP=0xFFFFFFFF`, `input=False`, `_NET_WM_USER_TIME=0`; геометрия выводится из workarea и surface scale. `scripts/smoke.py` проверяет это через xprop/xwininfo.

Отклонение: полноэкранное приложение **не** перекрывает полоску — Mutter 46 ставит `ABOVE` выше `FULLSCREEN`. Принято для v1; evidence — [acceptance.md](../acceptance.md), spec §16.
