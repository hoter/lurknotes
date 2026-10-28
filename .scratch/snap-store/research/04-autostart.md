# Автозапуск LurkNotes в strict-снапе

Дата проверки: 2026-10-28.
Машина: Ubuntu 24.04, GNOME 46, snapd 2.77.1+ubuntu24.04, `snapcraft` не установлен.
Код приложения: `src/lurkn/autostart.py`, `src/lurkn/cli.py`, `src/lurkn/app.py`
(в этом отчёте не менялся).

**Короткий вывод.** `apps.<app>.autostart` — это только имя desktop-файла, который
приложение само кладёт в `$SNAP_USER_DATA/.config/autostart/`. Snapd не поставляет этот
файл и не создаёт его: без записи из приложения объявление — no-op. При логине
`/etc/xdg/autostart/snap-userd-autostart.desktop` запускает `snap userd --autostart`,
тот находит файлы во всех `~/snap/*/current/.config/autostart/*.desktop`, матчит их по
`basename` с `autostart:` в `meta/snap.yaml` и запускает **обёртку приложения плюс
аргументы из `Exec=` без первого токена**. Значит `--autostart` (только полоска)
получится только если он явно стоит в `Exec=`; snapd сам его не добавляет. Отключить
автозапуск можно удалением файла или `Hidden=true`/`X-GNOME-Autostart-enabled=false`,
но не через `snap set` и не через Store permissions: автозапуск — не интерфейс.
Для «включён по умолчанию» приложение должно писать файл само при первом запуске;
текущий `--install-autostart` под snap нужно убрать, а запись файла перенести в
обычный старт.

---

## 1. Семантика `apps.<name>.autostart`

**Тип и значение.** В схеме snapcraft это `string | null`, по умолчанию `null`:

```json
"autostart": {
  "anyOf": [{"type": "string"}, {"type": "null"}],
  "default": null,
  "description": "The desktop file used to start an app when the desktop environment starts."
}
```

Источник: [`schema/snapcraft.json`](https://github.com/canonical/snapcraft/blob/main/schema/snapcraft.json).
Документация поля в моделях snapcraft:

> The desktop file is placed in `$SNAP_USER_DATA/.config/autostart` and the app is
> launched by the app's command wrapper (`<name>.<app>`) plus any argument present
> in the `Exec=` line in the `.desktop` file when the desktop environment is started.

Источник: [`snapcraft/models/project.py`](https://github.com/canonical/snapcraft/blob/main/snapcraft/models/project.py)
(класс `App`, поле `autostart`); в docs это `apps.<app-name>.autostart`
([reference/snapcraft-yaml.rst](https://github.com/canonical/snapcraft/blob/main/docs/reference/snapcraft-yaml.rst)).
Там же пример: `autostart: foo-app.desktop`.

**Что важно из формулировки:**

- значение — **имя файла**, не путь и не «включить автозапуск»;
- файл лежит **не в снапе**, а в пользовательских данных (`$SNAP_USER_DATA`);
- snapd не проверяет существование файла ни при сборке, ни при установке:
  `snapcraft`/`snapd` видят только строку в `meta/snap.yaml`;
- «включён по умолчанию» = приложение создаёт файл; объявление лишь разрешает
  snapd его подхватить.

**Как snapd матчит файл.** `usersession/autostart/autostart.go`:

```go
glob := filepath.Join(usrSnapDir, "*/current/.config/autostart/*.desktop")
...
for _, candidate := range info.Apps {
    if candidate.Autostart == desktopFile {   // desktopFile = filepath.Base(...)
        app = candidate
        break
    }
}
if app == nil {
    return nil, fmt.Errorf("cannot match desktop file with snap %s applications", instanceName)
}
```

Источник: [`usersession/autostart/autostart.go`](https://github.com/canonical/snapd/blob/master/usersession/autostart/autostart.go).
Следствия:

- сравнивается **только `basename`**; каталог значения не важен, регистр важен;
- файл должен лежать именно под `current` (симлинк на текущую ревизию), а не в
  `common` и не в конкретной ревизии напрямую;
- несовпадение не ломает другие снапы: ошибка попадает в журнал, остальные
  приложения всё равно стартуют (`failedApps` собирается, но цикл продолжается);
- `apps.<name>.autostart` не делает приложение сервисом и не требует `daemon`.

Официальный раздел «Autostart desktop files» в
[The snap format](https://snapcraft.io/docs/reference/development/yaml-schemas/the-snap-format)
даёт тот же контракт и пример: `autostart: my-chat.desktop`, файл
`$SNAP_USER_DATA/.config/autostart/my-chat.desktop` с
`Exec=/usr/bin/my-chat --autostart a b c` запускается как
`my-chat.chat --autostart a b c`.

---

## 2. Desktop-файл: путь, `Exec`, `Icon`, остальные ключи

### 2.1 Путь

```
$SNAP_USER_DATA/.config/autostart/<autostart-значение>
= /home/<user>/snap/lurknotes/current/.config/autostart/dev.lurknotes.LurkNotes.desktop
```

- Каталог `$SNAP_USER_DATA` (`~/snap/<snap>/<revision>`) появляется **только после
  первого запуска снапа** — это прямо сказано в
  [Data locations](https://snapcraft.io/docs/reference/administration/data-locations/):
  «Both `SNAP_USER_COMMON` and `SNAP_USER_DATA` only become available after a snap
  has been run once». Значит файл нельзя положить install-хуком «за пользователя»:
  хуки выполняются от root и не знают всех пользователей.
- `current` — симлинк на активную ревизию; при `snap refresh` snapd копирует
  пользовательские данные в новую ревизию (задача `doCopySnapData` в
  [`overlord/snapstate/handlers.go`](https://github.com/canonical/snapd/blob/master/overlord/snapstate/handlers.go)),
  поэтому файл переживает обновление. Не проверено на живой машине (см. §9).
- Файл в снапе (`snap/gui/*.desktop`) — это **другая** запись, для меню
  приложений; snapd её в автозапуск не ставит.

### 2.2 `Exec`

`autostart.go` вызывает `de.ExpandExec(nil)`, затем **выбрасывает `argv[0]`**:

```go
// NOTE: Ignore the actual argv[0] in Exec=.. line and replace it with a
// command of the snap application. Any arguments passed in the Exec=..
// line to the original command are preserved.
cmd := exec.Command(app.WrapperPath(), args[1:]...)
```

То есть:

| `Exec=` в файле | что реально запустится |
| --- | --- |
| `/usr/bin/lurknotes --autostart` | `/snap/bin/lurknotes --autostart` |
| `/snap/bin/lurknotes --autostart` | `/snap/bin/lurknotes --autostart` |
| `lurknotes` | `/snap/bin/lurknotes` (без флагов) |
| `/snap/lurknotes/12/bin/lurknotes --autostart` | `/snap/bin/lurknotes --autostart` |

Практические выводы:

- **`--autostart` не добавляется автоматически.** Если его нет в `Exec=`, приложение
  стартует как обычное.
- Абсолютный путь в `Exec=` для snapd декоративен: он всё равно подменяется
  обёрткой. Поэтому нынешний `launcher_path()` (см. §8), который может записать
  путь внутри ревизии, для snap-автозапуска безопасен, но вводит в заблуждение.
- `%U`/`%F` при `ExpandExec(nil)` разворачиваются в пусто; в autostart-файле они не
  нужны.
- Первый токен всё равно должен быть синтаксически корректным: парсер
  desktop-entry раскрывает кавычки/экранирование, пустой `Exec=` — ошибка
  (`desktop file %q has no Exec line`).

### 2.3 `Icon`

`Icon` snapd в автозапуске **не читает** (в `DesktopEntry` поле есть, но
`autostartCmd` его не использует). Требований к нему нет; можно не указывать.
Если файл когда-нибудь покажут в UI списка автозапуска, разумно дать имя иконки,
которое есть на хосте, но для snap-пути это не нужно.

Для **записи в меню** (отдельный файл в `snap/gui/`) правила другие — см. §7:
`Icon=${SNAP}/meta/gui/lurknotes.png`; snapd при установке переписывает это в
`/snap/lurknotes/current/meta/gui/lurknotes.png` (наблюдаемо, например, в
`/var/lib/snapd/desktop/applications/ktorrent_ktorrent.desktop` на этой машине).

### 2.4 Какие ключи вообще учитываются

`desktopentry.ShouldAutostart` (источник:
[`desktop/desktopentry/desktopentry.go`](https://github.com/canonical/snapd/blob/master/desktop/desktopentry/desktopentry.go)):

```go
if de.Hidden { return false }
if !de.GnomeAutostartEnabled && contains(currentDesktop, "GNOME") { return false }
if de.OnlyShowIn != nil && !isOneOfIn(currentDesktop, de.OnlyShowIn) { return false }
if de.NotShownIn != nil && isOneOfIn(currentDesktop, de.NotShownIn) { return false }
```

- `Hidden=true` — уважается всегда (это же рекомендует
  [Autostart spec §2.3](https://specifications.freedesktop.org/autostart-spec/latest/)).
- `X-GNOME-Autostart-enabled=false` — уважается **только** когда
  `XDG_CURRENT_DESKTOP` содержит `GNOME` (на Ubuntu это `ubuntu:GNOME`).
- `OnlyShowIn=GNOME;` / `NotShowIn=` — уважаются; `XDG_CURRENT_DESKTOP` режется по
  `:`. `OnlyShowIn=GNOME;` означает «не автозапускать в KDE/других сессиях».
- `TryExec`, `DBusActivatable`, `Implements` — **не поддерживаются**; для
  `meta/gui` snapd их молча вырезает (раздел «Unsupported desktop keys» в
  The snap format), а в autostart-файле парсер их просто игнорирует. То есть
  битый `TryExec` ничего не защищает.
- `NoDisplay`, `StartupNotify`, `Terminal`, `Type`, `Name`, `Comment` — на решение
  об автозапуске не влияют; безвредны (и полезны, если файл откроют в редакторе
  списка автозапуска).
- Неизвестные группы игнорируются; дубли `[Desktop Entry]` — ошибка парсинга;
  файл должен быть обычным UTF-8 desktop-файлом.

---

## 3. Когда snapd запускает приложение

Механизм — **не systemd-юнит**, а обычная запись в системном autostart-каталоге.
На проверенной машине:

```
$ cat /etc/xdg/autostart/snap-userd-autostart.desktop
[Desktop Entry]
Name=Snap user application autostart helper
Comment=Helper program for launching snap applications that are configured to start automatically.
Exec=/usr/bin/snap userd --autostart
Type=Application
NoDisplay=true
```

Тот же файл в исходниках snapd:
[`data/desktop/snap-userd-autostart.desktop.in`](https://github.com/canonical/snapd/blob/master/data/desktop/snap-userd-autostart.desktop.in).

Последовательность:

1. Пользователь логинится в графическую сессию (GDM → GNOME).
2. gnome-session запускает записи из `/etc/xdg/autostart` и `~/.config/autostart`,
   среди них — `snap userd --autostart` (от имени пользователя, без sudo).
3. `snap userd --autostart` — **one-shot**: обходит `~/snap/*/current/.config/autostart/*.desktop`
   (и `~/.snap/data`, если включён) и запускает приложения; сам демоном не остаётся
   (источник: [`cmd/snapd/cli/cmd_userd.go`](https://github.com/canonical/snapd/blob/master/cmd/snapd/cli/cmd_userd.go),
   `case x.Autostart: ... return x.runAutostart(usrSnapDirs)`).
4. Каждое приложение форкается и не ожидается; stdout/stderr идут в журнал
   пользователя с идентификатором, равным имени desktop-файла
   (`makeStdStreams(desktopFile)`).
5. Ошибки по одному файлу не мешают остальным; в конце `userd` печатает сводку
   `autostart failed: ...` (в журнал сессии).

Следствия для LurkNotes:

- автозапуск происходит **только при графическом логине**, не при загрузке и не
  сразу после `snap install`;
- после установки и **первого ручного запуска** (который создаёт файл) приложение
  стартует со **следующего** логина;
- у каждого пользователя свой `~/snap` и свой файл — «включено» не глобально;
- порядок относительно других autostart-приложений не определён; задержек и
  ретраев нет;
- если snap установлен, но пользователь ни разу его не запускал, автозапуска нет
  вообще (нет `SNAP_USER_DATA`, нет файла).

Эмпирика на машине: `snap userd --autostart` от обычного пользователя завершается
кодом 0 и ничего не запускает, если файлов нет.

---

## 4. Можно ли получить `--autostart` (только полоска)

Да. Это единственный поддерживаемый способ:

- положить в `Exec=` строку с `--autostart`;
- snapd сохранит все аргументы после первого токена.

Ни `autostart:`, ни какой-либо другой ключ snapcraft не умеет «добавить флаг».
Текущий `desktop_contents()` уже пишет `Exec=... --autostart`, и `cli.py` понимает
`--autostart` как «тихий» старт (strip only, без фокуса) — эта часть под snap
работает без изменений.

Ограничение: аргументы берутся из файла, который пишет само приложение, поэтому
«тихий» старт — ответственность приложения, а не манифеста.

---

## 5. Как пользователь выключает автозапуск

В snapd **нет** настройки, флага или permission для этого. Проверено по коду:
единственный потребитель — `autostart.go`, читающий файл; `snap set` тут ни при
чём, `snap disable` относится только к сервисам.

Доступные способы:

| Способ | Что делает | Ограничение |
| --- | --- | --- |
| `rm ~/snap/lurknotes/current/.config/autostart/dev.lurknotes.LurkNotes.desktop` | следующий логин без автозапуска | приложение может пересоздать файл при следующем запуске |
| `Hidden=true` в файле | snapd игнорирует файл (spec §2.3) | приложение может перезаписать файл |
| `X-GNOME-Autostart-enabled=false` | то же, но только в GNOME-сессии | то же |
| GNOME Tweaks → Startup Applications → выключить «Snap user application autostart helper» | отключает автозапуск **всех** snap-приложений | глобально, не только LurkNotes |
| настройка внутри приложения | «правильный» UX (так делает Slack/indicator-sensors) | в LurkNotes такой настройки сейчас нет |

Важно: файл лежит **не** в `~/.config/autostart`, поэтому в GNOME-настройках
списка автозапуска отдельной строки «LurkNotes» не будет. Пользователь видит только
системный helper. Это же объясняет, почему «выключить в Tweaks» заденет все снапы.

Рекомендации для тикета 09 (решение, не реализация):

- приложение должно уважать уже существующий файл: если он есть и содержит
  `Hidden=true` или `X-GNOME-Autostart-enabled=false` — не перезаписывать;
- либо дать явный переключатель (CLI `--autostart on|off` / пункт меню), который
  пишет/удаляет файл;
- в README описать `rm`-путь и то, что GNOME-тумблер в Tweaks глобальный.

---

## 6. Store: permissions, листинг, ревью

**Автозапуск — не интерфейс.** В `meta/snap.yaml` это поле приложения, а не plug,
поэтому:

- в `snap connections lurknotes` ничего не появляется;
- в блоке Permissions на странице снапа в Store ничего не появляется;
- при установке нет ни запроса, ни `--classic`, ни подтверждения;
- `snap install lurknotes` не требует дополнительных действий.

Это подтверждается тем, что `autostart` — поле `AppInfo`, а не `PlugInfo`
([`snap/info.go`](https://github.com/canonical/snapd/blob/master/snap/info.go)),
и официальный пример в The snap format не упоминает ни одного интерфейса.

**Почему это лучше `personal-files`.** Ревьюер Snap Store (alexmurray) прямо
рекомендует этот механизм вместо доступа к `~/.config/autostart`:

> Granting write access to `~/.config/autostart/` would allow a snap to escape
> confinement by specifying any arbitrary command be run. Instead however, a snap
> can allow itself to be autostarted by specifying the autostart property within
> their snapcraft.yaml ... so your snap can simply create this file and as it
> resides in the snap's private storage location there is no need to use
> personal-files to access this.

Источник: [forum.snapcraft.io/t/27830](https://forum.snapcraft.io/t/27830) (2021-12-07).
То есть `autostart:` избавляет от plug'а `personal-files` и связанного с ним
одобрения Store
([personal-files interface](https://snapcraft.io/docs/reference/interfaces/personal-files-interface/)).

**Что триггерит ручное ревью (по документации):**

- `confinement: classic` — Store «flag for human review» явно описан в
  [Reviewing classic confinement snaps](https://snapcraft.io/docs/reference/administration/reviewing-classic-confinement-snaps/);
- super-privileged интерфейсы — «require specific approval from the Store before
  they can be distributed» ([super-privileged interfaces](https://snapcraft.io/docs/explanation/interfaces/super-privileged-interfaces/));
- `passthrough:` в `meta/snap.yaml` — автоматическое ревью это ловит; jdstrand:
  «Please note that passthrough is only valid in snapcraft.yaml, not
  meta/snap.yaml... If you remove that, then you snap will pass automated review»
  ([forum.snapcraft.io/t/15309](https://forum.snapcraft.io/t/15309), 2020). В том же
  треде автозапуск был настроен через `autostart:`, и претензия была именно к
  `passthrough`, а не к автозапуску.

**Про сам `autostart:` триггера в документации нет.** Публичный снап Slack
(`stable`, strict) содержит `autostart: slack.desktop` — проверено на этой машине:

```
$ grep -n autostart /snap/slack/current/meta/snap.yaml
13:    autostart: slack.desktop
```

Так же делает `indicator-sensors` (снап самого ревьюера):
[`snapcraft.yaml`](https://github.com/alexmurray/indicator-sensors/blob/master/snap/snapcraft.yaml).
Вывод: рассчитываем на автоматическое ревью; окончательно проверяется первой
загрузкой в `edge` (см. §9). **Неуверенность:** публичного первоисточника, который
явно говорит «autostart не флагается», нет — только отсутствие упоминаний и
практика опубликованных снапов.

Отдельно: в описании листинга стоит явно написать, что приложение стартует при
логине (и как это выключить) — иначе для пользователя это невидимое поведение.

---

## 7. Конкретный манифест

### 7.1 `snapcraft.yaml` (фрагмент)

```yaml
name: lurknotes
title: LurkNotes
base: core24
confinement: strict
grade: stable
license: MIT

apps:
  lurknotes:
    command: bin/lurknotes
    extensions: [gnome]
    # Имя файла, который приложение само пишет в
    # $SNAP_USER_DATA/.config/autostart/. Не путь.
    autostart: dev.lurknotes.LurkNotes.desktop
    plugs:
      - x11        # XWayland; см. тикет 02
      - desktop
      # home — только если реально нужен ~/Documents (тикеты 02/08)

parts:
  lurknotes:
    plugin: python
    source: .
    # ... зависимости/стадия — тикет 08
```

`autostart` — поле уровня app; `snapcraft` просто переносит его в `meta/snap.yaml`.
Файл для автозапуска **не** кладётся в `snap/gui/` и не собирается snapcraft'ом.

### 7.2 Запись в меню приложений (не автозапуск)

`snap/gui/lurknotes.desktop` и `snap/gui/lurknotes.png` (256×256, <256 KB):

```ini
[Desktop Entry]
Type=Application
Name=LurkNotes
Comment=Notes deck at the edge of the screen
Exec=lurknotes
Icon=${SNAP}/meta/gui/lurknotes.png
Terminal=false
Categories=Utility;
```

Правило и форма `Icon=${SNAP}/meta/gui/<snap-name>.png` — из
[Configure package information](https://github.com/canonical/snapcraft/blob/main/docs/how-to/crafting/configure-package-information.rst).
Snapd перепишет при установке `Exec` в `/snap/bin/lurknotes` и `Icon` в
`/snap/lurknotes/current/meta/gui/lurknotes.png` (наблюдаемо на
`ktorrent_ktorrent.desktop`).

### 7.3 Файл, который приложение пишет в рантайме

`$SNAP_USER_DATA/.config/autostart/dev.lurknotes.LurkNotes.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=LurkNotes
Comment=Notes deck at the edge of the screen
Exec=/snap/bin/lurknotes --autostart
Terminal=false
NoDisplay=true
StartupNotify=false
X-GNOME-Autostart-enabled=true
OnlyShowIn=GNOME;
```

Это почти текущий вывод `desktop_contents()`. Отличия/замечания:

- `Exec` можно оставить и с путём внутри ревизии — snapd всё равно возьмёт только
  `--autostart`; но `/snap/bin/lurknotes` честнее и переживает ревизии, если файл
  прочитает кто-то ещё;
- `Icon` не нужен; если добавлять — только имя иконки, а не `${SNAP}` (snapd не
  раскрывает переменные в autostart-файле);
- `OnlyShowIn=GNOME;` — осознанный выбор под Ubuntu/GNOME; для других DE autostart
  молча выключен. Если нужна широкая поддержка — убрать ключ;
- `NoDisplay`/`StartupNotify`/`Type`/`Name`/`Comment` snapd игнорирует, но они
  безвредны;
- `X-GNOME-Autostart-enabled=true` важен: именно его пользователь/приложение может
  переключить в `false`, не удаляя файл.

---

## 8. Совместимость с текущим `--install-autostart` и `~/.config/autostart`

**Путь под snap.** Snapd для strict-снапа выставляет `HOME=$SNAP_USER_DATA`, а
`XDG_CONFIG_HOME` не выставляет (проверено на этой машине внутри `snap run --shell glab`):

```
HOME=/home/dev/snap/glab/6906
SNAP_USER_DATA=/home/dev/snap/glab/6906
SNAP_REAL_HOME=/home/dev
# XDG_CONFIG_HOME отсутствует
```

Источник: [`snap/snapenv/snapenv.go`](https://github.com/canonical/snapd/blob/master/snap/snapenv/snapenv.go)
(`userEnv`: `HOME = UserDataDir`, `XDG_RUNTIME_DIR`; `XDG_CONFIG_HOME` задаётся
только при `MigratedToExposedHome`). Поэтому `config_home()` в
`src/lurkn/autostart.py` даёт ровно `$SNAP_USER_DATA/.config` — тот каталог, который
сканирует snapd. То есть **текущая запись файла совместима со snap** без правок.

**Риск.** Если snapd когда-нибудь включит `MigratedToExposedHome`, `XDG_CONFIG_HOME`
станет `$SNAP_USER_DATA/xdg-config`, и файл уедет в каталог, который snapd не
сканирует. Для snap-сборки надёжнее игнорировать `XDG_CONFIG_HOME` и писать явно в
`$SNAP_USER_DATA/.config/autostart` (или в `~/.config`, т.к. `HOME` уже подменён).
На 24.04/snapd 2.77.1 миграция не активна — но это хрупкое место.

**`launcher_path()`.** Сейчас функция предпочитает `sys.argv[0]`, если это файл с
именем `lurknotes`, и делает `resolve()`. Под snap это может дать
`/snap/lurknotes/12/bin/lurknotes` — путь конкретной ревизии. Для snapd это
безвредно (`argv[0]` игнорируется), но файл становится неверным для любого
другого потребителя и путает при отладке. Для snap-сборки лучше писать
`/snap/bin/lurknotes`.

**Что делать с `--install-autostart`.** По решению карты для snap-сборки флаг
убирается. Но объявление `autostart:` само файл не создаёт: чтобы автозапуск был
«включён по умолчанию», запись файла нужно перенести в обычный первый запуск
(идемпотентно), а не оставлять только за `--install-autostart`. Иначе пользователь
получит автозапуск только после ручного `lurknotes --install-autostart`, что
противоречит цели.

**Сосуществование с deb/pipx.** У deb/pipx-версии файл лежит в
`~/.config/autostart/dev.lurknotes.LurkNotes.desktop`, у snap — в
`~/snap/lurknotes/current/.config/autostart/`. Это разные каталоги: при логине
могут стартовать **два** экземпляра (и оба будут бороться за один application id /
D-Bus имя). Это вопрос тикетов 03 и 09: либо миграция (удалять/не создавать
хостовый файл при наличии snap), либо разные id, либо явно документировать
«выберите одну установку».

Ещё нюанс: если snap-версия уже запущена, `--autostart` при логине попытается
стартовать второй процесс. Поведение зависит от single-instance логики
(`GApplication`/D-Bus); в рамках этого тикета не проверялось.

---

## 9. Как тестировать автозапуск на чистой Ubuntu 24.04

Нужен **графический** логин: cloud-образ в Multipass/LXD без desktop не подойдёт —
там нет gnome-session и `/etc/xdg/autostart` никто не исполняет. Варианты:

- чистая VM с Ubuntu 24.04 Desktop ISO (лучший вариант);
- либо новый Unix-пользователь на уже установленной 24.04: `sudo adduser snap-test`,
  вход через GDM. Для per-user автозапуска это даже чище: чистый `$HOME`, чистый
  `~/snap`, системный snap уже установлен.

### 9.1 Подготовка

```bash
sudo snap install --dangerous ./lurknotes_0.1.0_amd64.snap
# или, после публикации: sudo snap install --edge lurknotes
snap list lurknotes
grep -n "autostart:" /snap/lurknotes/current/meta/snap.yaml
# ожидается: autostart: dev.lurknotes.LurkNotes.desktop
```

### 9.2 Первый запуск (файл должен появиться)

Запустить из меню приложений (или `lurknotes`), затем:

```bash
ls -l ~/snap/lurknotes/current/.config/autostart/
cat ~/snap/lurknotes/current/.config/autostart/dev.lurknotes.LurkNotes.desktop
# ожидается строка Exec=... --autostart
```

Если файла нет — автозапуск не включён; это ошибка реализации, а не snapd.

### 9.3 Быстрая проверка без перелогина (не заменяет настоящий тест)

```bash
snap userd --autostart; echo "exit=$?"
sleep 2
pgrep -af lurknotes
journalctl --user -b -o cat | grep -i "dev.lurknotes.LurkNotes.desktop"
```

Так делает и spread-тест snapd
([`tests/main/snap-userd-desktop-app-autostart/task.yaml`](https://github.com/canonical/snapd/blob/master/tests/main/snap-userd-desktop-app-autostart/task.yaml)):
установить снап, один раз запустить (он создаёт файл), вызвать
`snap userd --autostart`, дождаться побочного эффекта. Запускать **от пользователя**,
не через sudo: `userd` читает `$HOME/snap` вызывающего.

### 9.4 Настоящий тест логина

```bash
gnome-session-quit --logout --no-prompt
# войти тем же пользователем
pgrep -af lurknotes
ps -o lstart=,args= -C lurknotes 2>/dev/null || ps -o lstart=,args= -p $(pgrep -n lurknotes)
journalctl --user -b | grep -i lurknotes
```

Проверить визуально: видна только полоска, фокус не украден, окно не по центру.
Полезно свериться с `scripts/acceptance.py`.

### 9.5 Негативные и краевые проверки

```bash
# 1. удаление файла выключает автозапуск
rm ~/snap/lurknotes/current/.config/autostart/dev.lurknotes.LurkNotes.desktop
# перелогин → процесса нет

# 2. Hidden=true уважается
printf 'Hidden=true\n' >> ~/snap/lurknotes/current/.config/autostart/dev.lurknotes.LurkNotes.desktop
# перелогин → процесса нет; затем проверить, не перезаписал ли файл сам app

# 3. обновление не теряет файл
sudo snap refresh lurknotes
ls ~/snap/lurknotes/current/.config/autostart/

# 4. несовпадение имени (диагностика)
# переименовать файл → в журнале "cannot match desktop file with snap ... applications"
```

Диагностика по сообщениям из `autostart.go`: `cannot match desktop file with snap
%s applications` (имя не совпало), `skipped` (Hidden/OnlyShowIn/NotShowIn),
`cannot parse desktop file` (синтаксис), `invalid application startup command`
(плохой `Exec`).

### 9.6 Ревью в Store

Первую загрузку делать в `edge`; в Dashboard посмотреть, не ушла ли ревизия в
manual review. Ожидание — автоматическое ревью (см. §6), но это единственный
способ проверить окончательно.

---

## 10. Неуверенности и что не проверено

1. **Ручное ревью Store для `autostart:`** — явного первоисточника «не флагается»
   нет. Есть опубликованные снапы (Slack, indicator-sensors) и отсутствие
   упоминаний в docs. Проверяется первой отправкой в `edge`.
2. **`MigratedToExposedHome` / `XDG_CONFIG_HOME`** — на 24.04 + snapd 2.77.1
   переменная не выставляется (проверено в `glab`), но поведение при включённой
   миграции не тестировалось; отсюда рекомендация писать в `$SNAP_USER_DATA`
   явно.
3. **Копирование файла при refresh** — подтверждено кодом (`doCopySnapData`), не
   проверено на живой машине.
4. **Два экземпляра (deb + snap)** — поведение single-instance при одновременном
   старте из двух autostart-каталогов не проверялось (тикеты 03/09).
5. **Порядок и задержка** относительно других autostart-приложений не
   специфицированы; полагаться на «до/после» нельзя.
6. **Листинг Store** — утверждение «автозапуск не отображается в permissions»
   следует из того, что это не интерфейс; вживую страницу своего снапа не
   проверяли (снап ещё не опубликован).
7. **Сборка** — `snapcraft` не установлен, манифест в §7 не собирался; это
   ответственность execution-захода.

---

## 11. Источники

Первоисточники (код и спеки):

- The snap format, «Autostart desktop files» и «Unsupported desktop keys» —
  <https://snapcraft.io/docs/reference/development/yaml-schemas/the-snap-format>
- snapd, `usersession/autostart/autostart.go` —
  <https://github.com/canonical/snapd/blob/master/usersession/autostart/autostart.go>
- snapd, `desktop/desktopentry/desktopentry.go` (`ShouldAutostart`, `ExpandExec`) —
  <https://github.com/canonical/snapd/blob/master/desktop/desktopentry/desktopentry.go>
- snapd, `cmd/snapd/cli/cmd_userd.go` (`--autostart`, one-shot) —
  <https://github.com/canonical/snapd/blob/master/cmd/snapd/cli/cmd_userd.go>
- snapd, `/etc/xdg/autostart/snap-userd-autostart.desktop` —
  <https://github.com/canonical/snapd/blob/master/data/desktop/snap-userd-autostart.desktop.in>
  (и файл на машине: `/etc/xdg/autostart/snap-userd-autostart.desktop`)
- snapd, окружение strict-снапа (`HOME`, `XDG_CONFIG_HOME`) —
  <https://github.com/canonical/snapd/blob/master/snap/snapenv/snapenv.go>
- snapd, копирование пользовательских данных при refresh —
  <https://github.com/canonical/snapd/blob/master/overlord/snapstate/handlers.go>
- snapd, spread-тест автозапуска —
  <https://github.com/canonical/snapd/blob/master/tests/main/snap-userd-desktop-app-autostart/task.yaml>
- Desktop Application Autostart Specification (Hidden, OnlyShowIn, NotShowIn) —
  <https://specifications.freedesktop.org/autostart-spec/latest/>
- snapcraft, схема (`autostart`: string|null) —
  <https://github.com/canonical/snapcraft/blob/main/schema/snapcraft.json>
- snapcraft, docstring поля `App.autostart` —
  <https://github.com/canonical/snapcraft/blob/main/snapcraft/models/project.py>
- snapcraft, desktop-файл и иконка в `snap/gui/` —
  <https://github.com/canonical/snapcraft/blob/main/docs/how-to/crafting/configure-package-information.rst>

Документация Store:

- Reviewing classic confinement snaps —
  <https://snapcraft.io/docs/reference/administration/reviewing-classic-confinement-snaps/>
- Super-privileged interfaces —
  <https://snapcraft.io/docs/explanation/interfaces/super-privileged-interfaces/>
- personal-files interface —
  <https://snapcraft.io/docs/reference/interfaces/personal-files-interface/>
- Data locations (когда появляется `SNAP_USER_DATA`) —
  <https://snapcraft.io/docs/reference/administration/data-locations/>

Практика (ревьюеры и опубликованные снапы):

- alexmurray о `autostart` вместо `personal-files` —
  <https://forum.snapcraft.io/t/27830>
- jdstrand о `passthrough` и automated review — <https://forum.snapcraft.io/t/15309>
- indicator-sensors: `autostart:` + запись файла через `g_get_user_config_dir()` —
  <https://github.com/alexmurray/indicator-sensors/blob/master/snap/snapcraft.yaml>,
  <https://github.com/alexmurray/indicator-sensors/blob/master/indicator-sensors/is-application.c>
- Slack в `stable` с `autostart: slack.desktop` — локально
  `/snap/slack/current/meta/snap.yaml`

Локальные проверки на машине (2026-10-28):

```
snap 2.77.1+ubuntu24.04
snapd 2.77.1+ubuntu24.04
$ snap run --shell glab  →  HOME=/home/dev/snap/glab/6906, XDG_CONFIG_HOME не задан
$ snap userd --autostart  →  exit=0, файлов автозапуска нет
$ cat /etc/xdg/autostart/snap-userd-autostart.desktop  →  Exec=/usr/bin/snap userd --autostart
```
