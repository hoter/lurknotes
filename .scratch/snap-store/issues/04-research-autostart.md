# Research: автозапуск снапа

Type: research
Status: resolved
Blocked by:

Research branch: `research/autostart` (findings: `.scratch/snap-store/research/04-autostart.md`)

## Question

Как объявить автозапуск LurkNotes в strict-снапе и что это значит для
пользователя?

Проверить по первоисточникам (Snapcraft `apps.<name>.autostart`, snapd
autostart, desktop file spec):

- формат desktop-файла внутри снапа, требования к `Exec`/`Icon`;
- когда и как snapd запускает его при логине; запускается ли `--autostart`
  (только полоска) или обычный старт;
- можно ли пользователю выключить автозапуск (snap settings? удаление файла?);
- как это выглядит в Store permissions/листинге и триггерит ли ручное ревью;
- как тестировать автозапуск на чистой машине.

Ответ — отчёт с примером `snapcraft.yaml` и ограничениями.

## Answer

Resolved by research on branch `research/autostart`; full report:
<https://github.com/hoter/lurknotes/blob/research/autostart/.scratch/snap-store/research/04-autostart.md>

- `apps.<name>.autostart` stores only a desktop-file **basename**. snapd matches it
  against `~/snap/<name>/<revision>/.config/autostart/*.desktop`; it checks nothing
  at build or install time.
- The file is **not shipped in the snap**. It must be written into
  `$SNAP_USER_DATA/.config/autostart/` by the app on first run (that directory only
  exists after the first launch), so "enabled by default" means a runtime write.
- snapd drops `Exec=`'s `argv[0]` and runs the app command plus the remaining
  arguments. `--autostart` is passed only if it is literally in `Exec=`; snapd does
  not add it.
- Startup is at graphical login via `snap userd --autostart` scanning
  `/etc/xdg/autostart`; it is not a systemd unit. Disable by deleting the file or
  setting `Hidden=true` / `X-GNOME-Autostart-enabled=false`; there is no `snap set`
  switch and it is not a Store permission.
- Under the snap, `HOME=$SNAP_USER_DATA` and `XDG_CONFIG_HOME` is unset (verified
  inside another strict snap), so the current `autostart.py` path is already close;
  it should use `$SNAP_USER_DATA` explicitly and `/snap/bin/lurknotes` as the
  launcher. `--install-autostart` should move into the normal first run for the
  snap build, while remaining for deb/pipx.
- Autostart is not an interface and has no documented manual-review trigger (one
  reviewer recommends it over `personal-files` for `~/.config/autostart`); marked
  uncertain because public review docs do not enumerate it.
- A deb/pipx autostart entry can coexist and start a second instance; 03/09 must
  decide the coexistence policy.
