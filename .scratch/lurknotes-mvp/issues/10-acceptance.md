# 10: Приёмка и замеры

**What to build:** Подтверждённый MVP: все критерии спеки пройдены, бюджет старта и памяти измерен, известные дефекты записаны.

**Blocked by:** 05, 06, 07, 08, 09

**Triage:** ready-for-agent
**Status:** open

- [x] Все 12 критериев готовности из спеки пройдены и отмечены — 11/12 pass;
      критерий 11 (fullscreen) записан как accepted deviation с evidence,
      см. [acceptance.md](../acceptance.md#1-criterion-11-fullscreen-does-not-cover-the-strip-new-platform).
- [x] Измерены холодный и тёплый старт; холодный не дольше 1.5 с — cold
      median 174 ms, warm `new` delivery median 159 ms / visible 195 ms.
- [x] Измерена память в простое; не больше 120 МБ или зафиксировано отклонение
      с решением — 134.3 MB median; deviation + Rust-threshold decision
      записаны в acceptance.md.
- [x] `kill -9` во время записи не приводит к потере или порче файла — 15/15
      runs, main valid, 14/15 backups valid (one kill before the first backup
      copy), 4 kills left a temp file; structural guarantee documented.
- [x] Проверено, что приложение не открывает сетевых соединений — 6 AF_UNIX
      (D-Bus), 0 AF_INET/AF_INET6; `lsof -a -i` empty.
- [x] Принятые дефекты записаны: передача фокуса полоске при сворачивании,
      полноэкранные приложения, память, fixed peek pane, strip-release cancel,
      All Notes overlap, manual hotkey/autostart steps.

**Result:** [acceptance.md](../acceptance.md). Status intentionally left
`open`; final closure is a separate step.
