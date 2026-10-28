# Research: автозапуск снапа

Type: research
Status: open
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
