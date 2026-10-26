# 10: Приёмка и замеры

**What to build:** Подтверждённый MVP: все критерии спеки пройдены, бюджет старта и памяти измерен, известные дефекты записаны.

**Blocked by:** 05, 06, 07, 08, 09

**Triage:** ready-for-agent
**Status:** resolved

- [x] Все 12 критериев проверены: 11 pass, критерий 11 — принятое отклонение (fullscreen);
      критерий 11 (fullscreen) записан как accepted deviation с evidence,
      см. [acceptance.md](../acceptance.md#1-criterion-11-fullscreen-does-not-cover-the-strip-new-platform).
- [x] Измерены холодный и тёплый старт; холодный не дольше 1.5 с — cold
      median 174 ms, warm `new` delivery median 149 ms / visible 190 ms.
- [x] Измерена память в простое; не больше 120 МБ или зафиксировано отклонение
      с решением — 134.5 MB median; deviation + Rust-threshold decision
      записаны в acceptance.md.
- [x] `kill -9` во время записи не приводит к потере или порче файла — 15/15
      runs, main valid, 14/15 backups valid (one kill before the first backup
      copy), 4 kills left a temp file; structural guarantee documented.
- [x] Проверено, что приложение не открывает сетевых соединений — 6 AF_UNIX
      (D-Bus), 0 AF_INET/AF_INET6; `lsof -a -i` empty.
- [x] Принятые дефекты записаны: передача фокуса полоске при сворачивании,
      полноэкранные приложения, память, fixed peek pane, strip-release cancel,
      All Notes overlap, manual hotkey/autostart steps.

**Result:** [acceptance.md](../acceptance.md). Closed 2026-10-27: 11/12 критериев, критерий 11 — принятое отклонение; см. Answer.

## Answer

Приёмка проведена 2026-10-27. 11 из 12 критериев §12 пройдены; критерий 11 (fullscreen перекрывает колоду) **не достигнут**: Mutter 46 держит `ABOVE` выше `FULLSCREEN`, полоска остаётся видимой. Принято как отклонение v1 под риск-фолбэк плана (GNOME Shell extension вне MVP), зафиксировано в [acceptance.md](../acceptance.md) и spec §16.

Измерено: холодный старт 174 мс (≤1.5 с), тёплый `new` 149 мс delivery / 190 мс visible (≤300 мс), autosave 379 мс, idle RSS 134.5 МБ (цель 120 — отклонение принято), idle CPU 0%, 0 INET-сокетов, `kill -9` 15/15 coherent mains. Все 12 пунктов и принятые дефекты записаны; 221 pytest + 9 живых прогонов.
