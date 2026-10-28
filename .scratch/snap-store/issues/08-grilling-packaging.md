# Grilling: форма snap-рецепта

Type: grilling
Status: open
Blocked by: 01, 02

## Question

Выбрать итоговую форму `snapcraft.yaml` по результатам 01 и 02:

- base/extension (`core24` + `gnome`), python plugin vs stage-packages;
- какие plugs (`x11`, `desktop`, `home`?) и нужен ли `personal-files`;
- как называется app/command (`lurknotes`), совпадает ли app id;
- остаётся ли `--install-autostart` для не-snap установок и как snap-сборка
  его отключает;
- нужны ли изменения в `__main__`/`autostart.py`/онбординге.

Ответ — решение и патч-план для execution-захода (без реализации в карте).
