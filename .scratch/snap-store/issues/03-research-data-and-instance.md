# Research: данные и единый экземпляр в снапе

Type: research
Status: claimed
Claim: research in progress on research/data-and-instance
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
