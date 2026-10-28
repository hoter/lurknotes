# Research: данные и единый экземпляр в снапе

Type: research
Status: resolved
Blocked by:

Research branch: `research/data-and-instance` (findings: `.scratch/snap-store/research/03-data-and-instance.md`)

## Question

Где LurkNotes будет хранить `notes.json` в strict-снапе и что произойдёт с
существующими установками (GitHub deb/sdist, pipx)?

Выяснить по первоисточникам (snapcraft environment variables, `home` и
`personal-files` interfaces, snapd docs, Gtk.Application/D-Bus):

- какие `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `SNAP_USER_DATA` видит
  приложение; куда попадёт текущий `~/.local/share/lurknotes`;
- можно ли читать/писать старый `~/.local/share/lurknotes` без
  `personal-files`, и как выглядит запрос этого интерфейса;
- что происходит при refresh/remove снапа с данными;
- конфликтует ли `Gtk.Application` с id `dev.lurknotes.LurkNotes` между snap
  и deb/pipx (D-Bus single instance), и как это разрулить;
- нужна ли миграция данных для пользователей GitHub-релиза.

Ответ — отчёт с матрицей вариантов и ссылками.

## Answer

Resolved by research on branch `research/data-and-instance`; full report:
<https://github.com/hoter/lurknotes/blob/research/data-and-instance/.scratch/snap-store/research/03-data-and-instance.md>

- Under strict confinement `HOME=$SNAP_USER_DATA` (`~/snap/lurknotes/<rev>`);
  `XDG_DATA_HOME` is unset, while the desktop helper sets it to
  `$SNAP_USER_DATA/.local/share`. Current `store.default_path()` therefore
  resolves to `~/snap/lurknotes/<rev>/.local/share/lurknotes/notes.json`.
- The real `~/.local/share/lurknotes` is **not** readable/writable: the `home`
  interface covers non-hidden paths only. A live strict-snap probe got
  `Permission denied`.
- `personal-files` would expose it, but it is super-privileged, not
  auto-connected, needs an approved snap declaration and a manual
  `snap connect`; and the app still has to be pointed at
  `$SNAP_REAL_HOME/.local/share`. Skip it for 0.1.0.
- `snap refresh` copies `SNAP_USER_DATA`; `snap remove` deletes
  `~/snap/lurknotes` and `/var/snap/lurknotes` but snapd leaves an automatic
  snapshot for ~31 days (skipped by `--purge`). `snap revert` does **not** copy
  data back: it rolls the code back, not the notes.
- `Gtk.Application` requires owning `dev.lurknotes.LurkNotes`; a strict snap
  without a `dbus` slot gets `AccessDenied` and exits at startup. A `dbus` slot
  needs a Store snap declaration for a well-known name.
- Same app id as deb/pipx conflicts: snap-first makes the deb forward into the
  snap; deb-first can make the snap fail. Recommendation: give the snap its own
  id (e.g. `io.github.hoter.LurkNotes`), add a matching session `dbus` slot,
  keep data in `SNAP_USER_DATA`, and document manual migration. The exact id is
  for 10/08 to decide.
- Migration for existing users: copy `notes.json` to
  `~/snap/lurknotes/current/.local/share/lurknotes/`, remove the old autostart
  entry, and bind the hotkey to `/snap/bin/lurknotes` (it comes after
  `/usr/bin` and `~/.local/bin` on PATH).
- Risks: Store acceptance of `dev.lurknotes.*` without domain ownership is
  unconfirmed; the same-id conflict is policy-derived, not tested with two real
  builds; docs and snapd code disagree on revert data behavior.
