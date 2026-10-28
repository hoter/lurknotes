# Данные и единый экземпляр в strict-снапе LurkNotes

**Машина:** Ubuntu 24.04, GNOME 46, Wayland/XWayland, x86_64, snapd 2.77.1+ubuntu24.04, GLib 2.80.0.
**Дата проверки:** 2026-10-28.
**Метод:** опубликованная документация Canonical (snap-docs) и исходники snapd 2.77.1; исходники GLib; живые пробы `snap run --shell` на установленных strict-снапах (`glab`, `ktorrent`). Приложение и его код не менялись.

---

## Краткий вердикт

1. **Strict-снап видит `HOME=$SNAP_USER_DATA`**, то есть `~/snap/lurknotes/<revision>`. `XDG_DATA_HOME` сам snapd не выставляет (кроме экспериментального exposed-home); его может выставить desktop-helper расширения `gnome`/`kde` — в обоих случаях получается один и тот же путь.
2. Текущий `Store.default_path()` поэтому резолвится в **`~/snap/lurknotes/<revision>/.local/share/lurknotes/notes.json`**, а не в `~/.local/share/lurknotes/notes.json`. Старые данные deb/pipx-пользователя снап **не видит**.
3. `~/.local/share/lurknotes` **недоступен** strict-снапу с интерфейсом `home`: `.local` — скрытый каталог, а `home` даёт доступ только к не-скрытым путям. Это подтверждено live-пробой: `Permission denied` на чтение и запись.
4. Доступ к старому пути возможен только через **`personal-files`** — super-privileged интерфейс, который **не auto-connect**, требует ручного `snap connect` и approved snap declaration в Store. Для 0.1.0 это лишний риск и лишний шаг пользователя.
5. **`Gtk.Application` с id `dev.lurknotes.LurkNotes` в strict-снапе без `dbus`-слота не запустится вообще.** `GApplication` вызывает `RequestName` на session bus; AppArmor strict-снапа без `dbus`-слота запрещает этот вызов, GLib считает ошибку регистрации фатальной и выходит с кодом 1. Это подтверждено live-пробой через `dbus-send` внутри strict-снапа.
6. С `dbus`-слотом снап сможет владеть именем, но **Store требует snap declaration** на well-known D-Bus name (manual review). То же имя, что у deb/pipx, создаёт конфликт единого экземпляра: второй билд либо падает, либо передаёт свой argv первому — вместе с чужим файлом заметок.
7. **Рекомендация:** отдельный application id для snap-сборки (через `LURKNOTES_APP_ID`, без правки кода), `dbus`-слот на это имя, данные в `SNAP_USER_DATA`, ручная миграция `notes.json` для желающих. `personal-files` в 0.1.0 не подключать.
8. **Refresh** копирует `SNAP_USER_DATA` в новую ревизию; **revert** данные не переносит (откат кода, не данных); **remove** удаляет `~/snap/lurknotes` и `/var/snap/lurknotes`, но оставляет автоматический snapshot на ~31 день (если не `--purge`). Это не пользовательский бэкап: для восстановления нужен `sudo snap restore`.

---

## 1. Что видит strict-снап

### 1.1 Переменные

| Переменная | Значение в strict-снапе | Источник |
|---|---|---|
| `HOME` | `$SNAP_USER_DATA` = `/home/<user>/snap/<snap>/<revision>` | snapd переписывает `HOME` для не-classic снапов; [environment variables](https://github.com/canonical/snap-docs/blob/main/docs/reference/development/environment-variables.md), [snapenv.go](https://github.com/canonical/snapd/blob/2.77.1/snap/snapenv/snapenv.go) |
| `SNAP_USER_DATA` | `/home/<user>/snap/<snap>/<revision>` | то же |
| `SNAP_USER_COMMON` | `/home/<user>/snap/<snap>/common` | то же |
| `SNAP_REAL_HOME` | реальный домашний каталог, `/home/<user>` | snapd 2.46+ |
| `XDG_RUNTIME_DIR` | `/run/user/<uid>/snap.<snap>` | snapd переписывает для не-classic |
| `XDG_DATA_HOME` | **не выставляется snapd**; desktop-helper ставит `$SNAP_USER_DATA/.local/share` | snapenv.go: только при `MigratedToExposedHome`; [desktop-exports](https://github.com/canonical/snapcraft/blob/main/extensions/desktop/common/desktop-exports) |
| `XDG_CONFIG_HOME` | **не выставляется snapd**; desktop-helper ставит `$SNAP_USER_DATA/.config` | live `desktop-launch` из `gnome-42-2204` |
| `XDG_CACHE_HOME` | не выставляется snapd; desktop-helper ставит `$SNAP_USER_COMMON/.cache` | [desktop-exports](https://github.com/canonical/snapcraft/blob/main/extensions/desktop/common/desktop-exports) |

Без desktop-helper'а `XDG_CONFIG_HOME`/`XDG_CACHE_HOME` не выставлены; config-fallback — `$HOME/.config` (тот же путь), cache-fallback — `$SNAP_USER_DATA/.cache` (не common). Для заметок это не важно.

Ключевой фрагмент `snapenv.go` (2.77.1):

```go
if !info.NeedsClassic() {
    // Snaps using strict or devmode confinement get an override for both
    // HOME and XDG_RUNTIME_DIR.
    env["HOME"] = info.UserDataDir(home, opts)
    env["XDG_RUNTIME_DIR"] = info.UserXdgRuntimeDir(sys.Geteuid())
}
env["SNAP_REAL_HOME"] = home

if opts.MigratedToExposedHome {
    env["XDG_DATA_HOME"] = filepath.Join(info.UserDataDir(home, opts), "xdg-data")
    env["XDG_CONFIG_HOME"] = filepath.Join(info.UserDataDir(home, opts), "xdg-config")
    env["XDG_CACHE_HOME"] = filepath.Join(info.UserDataDir(home, opts), "xdg-cache")
    ...
}
```

`MigratedToExposedHome` — отдельная экспериментальная раскладка; на обычной Ubuntu 24.04 по умолчанию выключена. В ней данные лежали бы в `$SNAP_USER_DATA/xdg-data`, но для LurkNotes это не текущий сценарий.

### 1.2 Живые пробы

Обычный strict-снап без desktop-расширения (`glab`):

```console
$ snap run --shell glab -c 'echo HOME=$HOME; echo XDG_DATA_HOME=${XDG_DATA_HOME-unset}; ...'
HOME=/home/dev/snap/glab/6906
XDG_DATA_HOME=unset
XDG_CONFIG_HOME=unset
XDG_CACHE_HOME=unset
XDG_RUNTIME_DIR=/run/user/1000/snap.glab
SNAP_USER_DATA=/home/dev/snap/glab/6906
```

Strict-снап с desktop-расширением (`ktorrent`):

```console
$ snap run --shell ktorrent -c 'env | grep -E "XDG|HOME"'
HOME=/home/dev/snap/ktorrent/64
XDG_DATA_HOME=/home/dev/snap/ktorrent/64/.local/share
XDG_CONFIG_HOME=/home/dev/snap/ktorrent/64/.config
XDG_CACHE_HOME=/home/dev/snap/ktorrent/common/.cache
```

`XDG_DATA_HOME`, `XDG_CONFIG_HOME` и `XDG_CACHE_HOME` здесь выставляет не snapd, а `snap/command-chain/desktop-launch` из desktop-helper'а. В исходнике `desktop-exports`:

```sh
# Set XDG_DATA_HOME to local path
export XDG_DATA_HOME="$SNAP_USER_DATA/.local/share"
...
export XDG_CACHE_HOME="$SNAP_USER_COMMON/.cache"
```

а в живом `desktop-launch` из `gnome-42-2204` есть и config:

```sh
export XDG_CONFIG_HOME="$SNAP_USER_DATA/.config"
```

То есть helper фиксирует тот же `$SNAP_USER_DATA/.config`, который получился бы из fallback `HOME/.config`.

**Вывод:** и с расширением, и без него `XDG_DATA_HOME` указывает на `$SNAP_USER_DATA/.local/share` (явно или через fallback `HOME/.local/share`). Для LurkNotes это один и тот же путь.

### 1.3 Унаследованный `XDG_DATA_HOME`

`snap run` **не вычищает** унаследованные `XDG_*`. Если пользователь выставил `XDG_DATA_HOME` глобально (например, в `~/.profile`), snap увидит именно его:

```console
$ XDG_DATA_HOME=/tmp/opencode/probe-data snap run --shell glab -c 'echo $XDG_DATA_HOME'
/tmp/opencode/probe-data
```

С `gnome`-расширением `desktop-launch` перезапишет `XDG_DATA_HOME` на `$SNAP_USER_DATA/.local/share`, так что этот крайний случай закрыт. Без расширения — нет: приложение попытается открыть реальный путь и получит `EACCES` (см. §3), после чего уйдёт в read-only/in-memory режим.

**Практический вывод:** в `snapcraft.yaml` стоит явно зафиксировать `XDG_DATA_HOME`, чтобы не зависеть от окружения пользователя и от того, применяется ли desktop-helper:

```yaml
apps:
  lurknotes:
    environment:
      XDG_DATA_HOME: $SNAP_USER_DATA/.local/share
```

Если позже понадобится `SNAP_USER_COMMON`, одной этой переменной недостаточно: `desktop-launch` выполняется в command-chain и перезапишет её; нужен wrapper после command-chain. Для 0.1.0 это не требуется.

---

## 2. Куда резолвится текущий код

`src/lurkn/store.py:79-83`:

```python
def default_path() -> Path:
    """`$XDG_DATA_HOME/lurknotes/notes.json` (spec §5.1)."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "lurknotes" / "notes.json"
```

`Path.home()` на Unix берёт `HOME`, если он выставлен ([os.path.expanduser](https://docs.python.org/3/library/os.path.html#os.path.expanduser)). В strict-снапе `HOME` — это `SNAP_USER_DATA`.

| Что | В deb/pipx (сейчас) | В strict-снапе |
|---|---|---|
| `notes.json` | `~/.local/share/lurknotes/notes.json` | `~/snap/lurknotes/<rev>/.local/share/lurknotes/notes.json` |
| `notes.bak.json` | рядом | рядом, в `~/snap/...` |
| `notes.corrupt-*.json` | рядом | рядом, в `~/snap/...` |
| onboarding-маркер | `~/.local/share/lurknotes/onboarded` | `~/snap/lurknotes/<rev>/.local/share/lurknotes/onboarded` |
| autostart | `~/.config/autostart/dev.lurknotes.LurkNotes.desktop` | `~/snap/lurknotes/<rev>/.config/autostart/...` — **GNOME его не читает** |

`src/lurkn/onboarding.py:16-25` использует тот же `XDG_DATA_HOME`/`HOME`, поэтому маркер первого запуска тоже уедет в snap-данные. `src/lurkn/autostart.py:21-33` использует `XDG_CONFIG_HOME`/`HOME`, поэтому `--install-autostart` внутри снапа запишет файл в `$SNAP_USER_DATA/.config/autostart`, который **GNOME не читает**. Snapd userd умеет запускать приложения из этого каталога, но только если файл сопоставлен с полем `autostart:` в `snapcraft.yaml`. Для snap-сборки автозапуск должен объявляться в `snapcraft.yaml` (`autostart:`), а `--install-autostart` для snap-пользователей не документируется (см. тикет 08).

`src/lurkn/app.py:79`:

```python
APP_ID = os.environ.get("LURKNOTES_APP_ID") or "dev.lurknotes.LurkNotes"
```

Это единственная точка, через которую snap-сборка может сменить application id без правки кода.

---

## 3. Старый `~/.local/share/lurknotes`: доступ без `personal-files`

### 3.1 `home` не помогает

Интерфейс `home` даёт доступ к **не-скрытым** файлам пользователя в `$HOME` ([home interface](https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/home-interface.md)). В AppArmor-шаблоне (`interfaces/builtin/home.go`) правило выглядит так:

```
owner @{HOME}/[^s.]**  rwkl
```

Символьный класс `[^s.]` исключает имена, начинающиеся с `.`. Каталог `.local` — скрытый, поэтому `~/.local/share/lurknotes` не попадает под правило. `read: all` этого не меняет: он снимает только проверку owner и не открывает скрытые каталоги.

Live-проба внутри strict-снапа с `home` (`glab`):

```console
$ snap run --shell glab -c 'cat /home/dev/.local/share/lurknotes/notes.json'
cat: /home/dev/.local/share/lurknotes/notes.json: Permission denied

$ snap run --shell glab -c 'touch /home/dev/.local/share/lurknotes/probe'
touch: cannot touch '/home/dev/.local/share/lurknotes/probe': Permission denied
```

При этом не-скрытый `$HOME` виден:

```console
$ snap run --shell glab -c 'ls /home/dev | head'
Downloads
...
```

То есть запрет точечный: именно скрытый `.local`, а не весь домашний каталог.

### 3.2 Что происходит в приложении при отказе

`Store.load()` ловит `OSError` и бросает `StoreError`; `_load_notes` в `app.py` переводит приложение в `read_only`, оставляет колоду в памяти и пишет ошибку в stderr. Пользователь увидит «Save failed»/ошибку чтения, но приложение не упадёт. Это соответствует §10 спеки, но для миграции это плохой первый запуск: снап выглядит пустым и не сохраняет.

### 3.3 `personal-files`: как выглядит запрос

Интерфейс описан в [personal-files interface](https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/personal-files-interface.md). Он предназначен именно для «импортировать данные из старого приложения» и даёт доступ к указанным скрытым путям в реальном `$HOME`.

Пример из документации почти дословно про наш случай:

```yaml
plugs:
  dot-config-foo:
    interface: personal-files
    read:
    - $HOME/.config/foo
  dot-local-share-foo:
    write:
    - $HOME/.local/share/foo

apps:
  foo:
    plugs:
    - dot-config-foo
    slots:
    - dot-local-share-foo
```

Для LurkNotes:

```yaml
plugs:
  dot-local-share-lurknotes:
    interface: personal-files
    write:
    - $HOME/.local/share/lurknotes

apps:
  lurknotes:
    plugs:
    - dot-local-share-lurknotes
```

Затем:

```sh
snap connect lurknotes:dot-local-share-lurknotes
```

(в типичном случае `snap connect` выполняется через `sudo`; в документации пример без sudo, но это системная операция).

Важные свойства из документации и исходников:

- **Auto-connect: no**, **Super-privileged: yes**. Пользователь должен подключить интерфейс вручную; без подключения доступа нет.
- Для публикации в Store нужен **approved snap declaration**; имя plug'а должно быть описательным (`dot-local-share-lurknotes`), чтобы ревьюер понимал, что именно открывается.
- `$HOME` в атрибутах разворачивается в **реальный** домашний каталог (`@{HOME}` в AppArmor), а не в `SNAP_USER_DATA`; правило получает `owner`-проверку.
- При `write` snapd сам создаёт недостающие каталоги между `$HOME` и целевым путём (`.local/share`), если их нет.
- Это доступ ко всему каталогу, включая `notes.bak.json`, `notes.corrupt-*.json` и `onboarded`.

Даже с `personal-files` приложение по умолчанию **не пойдёт** в реальный `~/.local/share`: его `XDG_DATA_HOME`/`HOME` указывают внутрь снапа. Чтобы использовать старый путь, нужно либо выставить `XDG_DATA_HOME=$SNAP_REAL_HOME/.local/share` в окружении снапа, либо научить приложение читать `SNAP_REAL_HOME` (правка кода). То есть `personal-files` — необходимое, но не достаточное условие.

### 3.4 Чего не хватит

- `system-files` — для системных путей, не для пользовательского `$HOME`.
- `home` с `read: all` — скрытые каталоги всё равно закрыты.
- Портал документов — только файлы, явно выбранные пользователем в диалоге; для автоматического импорта не подходит.
- Симлинк из не-скрытого места на `.local/share/lurknotes` не обойдёт AppArmor: политика path-based, конечный скрытый путь всё равно запрещён.

---

## 4. Refresh, revert, remove

### 4.1 Refresh / revert

Документация обещает, что `SNAP_USER_DATA` «backed up and restored across `snap refresh` and `snap revert`» ([environment variables](https://github.com/canonical/snap-docs/blob/main/docs/reference/development/environment-variables.md)). Фактически **refresh** копирует данные в каталог новой ревизии, а **revert** — нет; ниже детали. При переходе на новую ревизию `copySnapData()` копирует `SNAP_DATA` и `SNAP_USER_DATA` (для каждого пользователя) в каталог новой ревизии ([snapdata.go](https://github.com/canonical/snapd/blob/2.77.1/overlord/snapstate/backend/snapdata.go)); common-каталоги общие и не копируются. Задача `copy-snap-data` добавляется только когда `!Flags.Revert` ([snap.go](https://github.com/canonical/snapd/blob/2.77.1/overlord/snapstate/snap.go)).

Практически:

- `notes.json` переживает refresh: новая ревизия получает копию.
- `~/snap/lurknotes/current` — симлинк на текущую ревизию; для миграции удобно использовать его, а не номер ревизии.
- Старые ревизии остаются на диске (по умолчанию 2), поэтому в `~/snap/lurknotes/<old-rev>` может лежать старая копия заметок. Приложение её не читает, но диск она занимает.
- `snap revert` **не переносит данные**. В коде snapd задача `copy-snap-data` добавляется только при обычном refresh/install и пропускается при revert (`if !sc.snapsup.Flags.Revert` в `overlord/snapstate/snap.go`). Старая ревизия после revert читает **свой старый каталог** `~/snap/lurknotes/<old-rev>`, то есть заметки на момент, когда эта ревизия была текущей. Правки, сделанные в новой ревизии, после revert **не видны**; они остаются в `~/snap/lurknotes/<new-rev>` и могут быть удалены при очистке старых ревизий. Документация формулирует это как «backed up and restored across refresh and revert», но фактический код на revert копирование не делает — расхождение, которое надо проверить на живой сборке. Практический вывод: `snap revert` — откат кода, а не данных; перед ним надо сохранить `notes.json` из текущей ревизии (или сделать `snap save` и затем `snap restore`, но restore тоже перезаписывает данные).
- **Refresh awareness** (snapd 2.57+) откладывает автоматический refresh, пока приложение запущено, и применяет его после закрытия (до 14 дней); ручной `snap refresh` при запущенном приложении выдаёт ошибку ([refresh awareness](https://github.com/canonical/snap-docs/blob/main/docs/explanation/how-snaps-work/refresh-awareness.md)). Это снижает риск «приложение пишет в старую ревизию после refresh», но не устраняет его полностью при принудительных сценариях.

### 4.2 Remove

Официально ([data locations](https://github.com/canonical/snap-docs/blob/main/docs/reference/administration/data-locations.md)):

- удаляются `/var/snap/<snap>/` и `/home/<user>/snap/`;
- автоматически создаётся snapshot, который хранится ~30 дней (в [create data snapshots](https://github.com/canonical/snap-docs/blob/main/docs/how-to-guides/manage-snaps/create-data-snapshots.md) указано 31 день; расхождение в документации, практический ориентир — месяц);
- `snap remove --purge` удаляет данные **без** snapshot.

Что попадает в snapshot ([create data snapshots](https://github.com/canonical/snap-docs/blob/main/docs/how-to-guides/manage-snaps/create-data-snapshots.md)):

- `SNAP_DATA`, `SNAP_COMMON`, `SNAP_USER_DATA`, `SNAP_USER_COMMON`;
- для каждой ревизии — только данные установленной ревизии + common;
- файлы под mount point'ами исключаются (snapd 2.77+).

Восстановление:

```sh
sudo snap saved                 # найти set id, Notes = auto
# при необходимости: переустановить snap
sudo snap restore <set-id>
```

Или экспорт в zip:

```sh
sudo snap export-snapshot <set-id> lurknotes-backup.zip
```

`snap restore` требует установленного снапа; после `snap remove` нужно сначала поставить снап заново. Snapshot'ы лежат в `/var/lib/snapd/snapshots` и принадлежат root — это не user-facing бэкап, а страховка на месяц. Если пользователь удалил снап через `--purge` или отключил автоснапшоты (`snap set system snapshots.automatic.retention=no`), заметки исчезнут.

### 4.3 Если использовать `personal-files` + реальный путь

Тогда `notes.json` лежит вне `~/snap` и `/var/snap`:

- `snap refresh` его не копирует (копировать нечего — путь общий);
- `snap remove` его **не удаляет** (он не в snap-каталогах);
- snapshot его **не включает**;
- зато его видят deb/pipx, и при одновременной работе двух билдов возможна потеря обновлений: атомарная замена защищает файл от порчи, но не от «последний записавший выиграл».

---

## 5. Единый экземпляр и D-Bus

### 5.1 Как работает текущий single instance

`LurkNotesApp` — `Gtk.Application` с `application_id=APP_ID` и `Gio.ApplicationFlags.HANDLES_COMMAND_LINE` (`src/lurkn/app.py:83-94`). GApplication:

- регистрируется на **session bus** под well-known именем, равным application id (`dev.lurknotes.LurkNotes`);
- использует object path, производный от id: `/dev/lurknotes/LurkNotes`;
- при старте вызывает `RequestName` с `DO_NOT_QUEUE`;
- если имя уже занято, становится «remote» и передаёт argv/активацию primary-экземпляру через `org.gtk.Application`/`org.freedesktop.Application`;
- если `RequestName` вернул ошибку (а не «имя занято»), регистрация считается неуспешной.

Фрагмент GLib (`gio/gapplicationimpl-dbus.c`):

```c
reply = g_dbus_connection_call_sync (impl->session_bus,
                                     DBUS_SERVICE_DBUS,
                                     DBUS_PATH_DBUS,
                                     DBUS_INTERFACE_DBUS,
                                     "RequestName",
                                     g_variant_new ("(su)", impl->bus_name, name_owner_flags),
                                     ...);
if (reply == NULL)
  return FALSE;
```

И `gio/gapplication.c`:

```c
if (!g_application_register (application, NULL, &error))
  {
    g_printerr ("Failed to register: %s\n", error->message);
    ...
    *exit_status = 1;
    return TRUE;
  }
```

То есть ошибка `RequestName` — фатальна, а не «работаем без D-Bus».

### 5.2 Strict-снап без `dbus`-слота

Базовая AppArmor-политика снапа не даёт владеть произвольным именем на session bus. Интерфейс `desktop` даёт доступ к bus-сокету и ограниченным вызовам, но не к `RequestName`; `unity7` разрешает `RequestName`, но bind только для `org.kde.StatusNotifierItem-[0-9]*`, а не для произвольного имени. Live-проба внутри strict-снапа `glab` (есть `home` + `desktop`, нет `dbus`-слота):

```console
$ snap run --shell glab -c '/usr/bin/dbus-send --session --print-reply \
    --dest=org.freedesktop.DBus /org/freedesktop/DBus \
    org.freedesktop.DBus.RequestName string:dev.lurknotes.Probe uint32:0'

Error org.freedesktop.DBus.Error.AccessDenied: An AppArmor policy prevents this
sender from sending this message to this recipient; ... member="RequestName" ...
label="snap.glab.glab (enforce)"
```

`GApplication` делает ровно такой `RequestName`. Значит, **snap-сборка LurkNotes в текущем виде (с `Gtk.Application` и любым application id) не запустится без `dbus`-слота**. Это касается даже `lurknotes --version`: регистрация происходит до `do_command_line`.

### 5.3 `dbus`-слот

Чтобы снап мог владеть именем, нужно объявить слот ([dbus interface](https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/dbus-interface.md)):

```yaml
slots:
  lurknotes-dbus:
    interface: dbus
    bus: session
    name: dev.lurknotes.LurkNotes

apps:
  lurknotes:
    slots: [lurknotes-dbus]
```

(слот можно объявить top-level, как у `ktorrent`; тогда его permanent-правила применяются ко всем приложениям снапа).

Snapd генерирует для такого слота AppArmor-правило:

```
# bind to a well-known DBus name: org.kde.ktorrent
dbus (bind)
    bus=session
    name=org.kde.ktorrent,
```

Это видно в живом профиле `/var/lib/snapd/apparmor/profiles/snap.ktorrent.ktorrent`; в `snap.yaml` у `ktorrent` есть:

```yaml
slots:
  session-dbus-interface:
    interface: dbus
    name: org.kde.ktorrent
    bus: session
```

Слоту не нужен `snap connect`, чтобы приложение самого снапа получило bind-правило: permanent-правила слота применяются к приложениям снапа. Connect нужен только другим снапам-потребителям.

**Но:** документация прямо говорит, что для публикации в Store нужен **snap declaration** и manual review на well-known D-Bus name. Без утверждённого declaration Store не даст снапу «заявить» это имя; точная форма отказа (блокировка ревизии на ревью или отказ в слоте) будет видна на первой загрузке. Это ещё один human-only шаг, которого нет в текущем чек-листе карты.

На classic-хосте (а Ubuntu 24.04 — classic) snapd добавляет в профиль strict-снапа classic-only правила, которые разрешают **получать** вызовы от unconfined-процессов по object path слота. Поэтому deb-версия (unconfined) может отправить `Activate`/`CommandLine` снапу, если снап владеет именем. Обратное — снап как secondary к deb — по политике не разрешено: permanent-правила слота дают `send` только к `org.freedesktop.DBus` (Properties/Introspect), а общего `send` к чужому well-known имени нет.

### 5.4 Матрица конфликта

Один и тот же id `dev.lurknotes.LurkNotes` у snap и deb/pipx означает одно и то же имя на одном session bus пользователя. Возможные сценарии:

| Кто запущен первым | Что происходит |
|---|---|
| Только deb | Работает как раньше; данные в `~/.local/share/lurknotes`. |
| Только snap (со слотом) | Работает; данные в `~/snap/lurknotes/<rev>/.local/share/lurknotes`. |
| deb, затем snap | Snap получает `RequestName` → `EXISTS` (не ошибка), пытается синхронизировать actions с deb-инстансом; у snap нет `dbus (send)` к этому имени → регистрация, скорее всего, падает, snap завершается с ошибкой. Это ожидаемый вывод из политики; точный сценарий надо проверить на двух реальных сборках. |
| snap, затем deb | Deb (unconfined) получает `EXISTS`, находит primary-снап и передаёт ему свой argv (по classic-only правилам snapd, которые разрешают снапу receive от unconfined; ожидаемо). Deb-процесс завершается, а заметка создаётся **в данных снапа**, не в старом `~/.local/share/lurknotes`. Пользователь может не заметить подмены файла. |
| Оба установлены, но запускаются по очереди | Оба работают, но показывают **разные колоды**: у каждого свой `notes.json`. |

Отсюда два вывода:

- **Одинаковый id несовместим с сосуществованием** snap и deb/pipx. Худший случай — snap-first: старый CLI/hotkey молча пишет в snap-данные.
- **Разный id** убирает конфликт: у каждого билда свой single instance и свой файл. Это делается только окружением:

```yaml
apps:
  lurknotes:
    environment:
      LURKNOTES_APP_ID: dev.lurknotes.LurkNotesSnap
```

Код при этом не меняется: `APP_ID` читает переменную. `autostart.APPLICATION_ID` — отдельная константа, поэтому имя autostart-файла deb-версии не меняется.

### 5.5 Про `bus-name` и `common-id`

В snapd 2.77 появилось поле `apps.<app>.bus-name` и переменная `SNAP_APP_BUS_NAME` ([environment variables](https://github.com/canonical/snap-docs/blob/main/docs/reference/development/environment-variables.md)). Это **не** замена `dbus`-слоту:

- `bus-name` используется при генерации systemd-юнита (`BusName=`) для daemon-приложений ([service_unit_gen.go](https://github.com/canonical/snapd/blob/2.77.1/wrappers/internal/service_unit_gen.go));
- AppArmor-политика владения именем по-прежнему генерируется из `dbus`-слота;
- `common-id` — это связь с `.desktop`/AppStream, к D-Bus отношения не имеет.

Для `Gtk.Application` нужен именно `dbus`-слот; `bus-name` в `snapcraft.yaml` ничего не разрешит.

### 5.6 Какой id выбрать

- **`dev.lurknotes.LurkNotesSnap`** — минимальное изменение, сохраняет бренд; но ревьюер может спросить, принадлежит ли издателю домен `lurknotes.dev` (reverse-DNS).
- **`io.github.hoter.LurkNotes`** (или `...LurkNotesSnap`) — привязан к GitHub-репозиторию `github.com/hoter/lurknotes`, который указан как homepage; ревьюеру проще проверить владение. Но это уже не «тот же» id, что у deb, — что для snap и требуется.

Точный выбор — решение карты/тикета 05 (store review); с точки зрения данных и single instance оба варианта равноценны. Важно, чтобы **имя `dbus`-слота совпадало с `LURKNOTES_APP_ID`**.

---

## 6. Миграция пользователей GitHub/deb/pipx

### 6.1 Ручная миграция (рекомендуется для 0.1.0)

Снап не видит старый путь; пользователь копирует файл сам, из обычного (не `snap run --shell`) терминала:

```sh
# 1. Закрыть старый LurkNotes и snap (если запущены)
# 2. Один раз запустить snap, чтобы появился ~/snap/lurknotes/current, и закрыть
mkdir -p ~/snap/lurknotes/current/.local/share/lurknotes
cp -a ~/.local/share/lurknotes/notes.json \
      ~/snap/lurknotes/current/.local/share/lurknotes/
# опционально: cp -a ~/.local/share/lurknotes/notes.bak.json ...
```

Что копировать:

- `notes.json` — обязательно;
- `notes.bak.json` — по желанию (следующее сохранение создаст новый бэкап);
- `notes.corrupt-*.json` — не нужно, если пользователь не хочет сохранить историю порчи;
- `notes.recovering` — **не копировать**: это маркер незавершённого восстановления, он может запустить восстановление из бэкапа;
- `onboarded` — не копировать, если хотим показать snap-пользователю первый запуск/подсказку про хоткей.

После копирования проверить, что snap видит заметки, и только потом удалять старую установку. Старый `~/.local/share/lurknotes` при удалении deb/pipx **не** удаляется — он остаётся резервной копией.

### 6.2 Что ещё надо сделать пользователю

- **Убрать старый autostart:** `~/.config/autostart/dev.lurknotes.LurkNotes.desktop` (или отключить в GNOME Tweaks). Иначе после логина будут запускаться два LurkNotes (у snap свой autostart через snapd).
- **Поправить хоткей:** если `Ctrl+Alt+N` был привязан к `lurknotes new`, после установки snap команда всё ещё может находить старый бинарник. На Ubuntu `/snap/bin` идёт **после** `/usr/bin` и `~/.local/bin`, поэтому старый deb/pipx выигрывает. Надёжно: `snap run lurknotes new` или `/snap/bin/lurknotes new`; лучше — удалить старую установку.
- **Удалить старый пакет:** `pipx uninstall lurknotes` или `sudo apt remove lurknotes` (пакет называется по `pyproject.toml`; проверить `dpkg -l | grep lurknotes`). Данные при этом остаются.
- **Проверить, что в GNOME не осталось двух записей** в списке приложений: у deb `.desktop` — `dev.lurknotes.LurkNotes.desktop`, у snap — сгенерированный `lurknotes_lurknotes.desktop` (или с `common-id`). Для фонового приложения это не критично, но две autostart-записи — критично.

### 6.3 Обратный переезд

Перед удалением snap:

```sh
cp -a ~/snap/lurknotes/current/.local/share/lurknotes/notes.json \
      ~/.local/share/lurknotes/
```

(старый файл будет перезаписан; при желании сохранить его — `cp` в сторону). После `snap remove` snap-данные удалятся, но у deb/pipx останется актуальная копия. Если snap уже удалён, остаётся `sudo snap restore` (в течение ~31 дня) или `snap export-snapshot`.

### 6.4 Автоматический импорт (на будущее)

Возможен только с `personal-files` (read или write) и правкой кода:

1. При старте, если `notes.json` в snap-данных отсутствует, проверить `$SNAP_REAL_HOME/.local/share/lurknotes/notes.json`.
2. Если файл читается — скопировать в `$SNAP_USER_DATA/.local/share/lurknotes/notes.json` (или использовать его напрямую при write-плаге).
3. Показать пользователю, что импорт произошёл, и больше не повторять (маркер).

Для 0.1.0 это лишний код, лишний review и лишний `snap connect`; ручная миграция проще и прозрачнее.

---

## 7. Матрица вариантов

| # | Вариант | Где `notes.json` | Старые данные | Review / разрешения | Сосуществование с deb/pipx | Миграция | Главные минусы |
|---|---|---|---|---|---|---|---|
| **A** | **Strict, snap-local, свой app id, `dbus`-слот** (рекомендуется) | `~/snap/lurknotes/<rev>/.local/share/lurknotes/` | Не видны | `dbus` snap declaration (manual) | Да, если id разный; два autostart'а надо развести | Ручной `cp` | Отдельная колода; пользователь должен скопировать файл; два билда могут запускаться одновременно; `snap revert` не переносит данные |
| **B** | Strict, snap-local, **тот же** app id, `dbus`-слот | То же | Не видны | `dbus` snap declaration | **Нет:** deb-first → snap падает; snap-first → deb пишет в snap-данные | Ручной `cp` | Худший вариант: молчаливая подмена данных |
| **C** | Strict, **без** `dbus`-слота (как есть) | — | — | — | — | — | **Snap не запускается:** `RequestName` → AccessDenied → GLib exit 1 |
| **D** | Strict + `personal-files` **write** + `XDG_DATA_HOME=$SNAP_REAL_HOME/.local/share`, свой app id, `dbus`-слот | `~/.local/share/lurknotes/` (реальный) | Видны, используются на месте | `dbus` + `personal-files` (super-privileged, manual `snap connect`, два declaration'а) | Да, но **общий файл**: при одновременной работе потеря обновлений | Не нужна | Лишний review; лишний шаг `snap connect`; риск гонки; удаление snap не удаляет данные; snapshot их не включает |
| **E** | Strict + `personal-files` **read** + импорт при первом запуске (правка кода), свой app id, `dbus`-слот | Сначала реальный, потом snap-local | Импортируются один раз | `dbus` + `personal-files` (read; review + `snap connect`) | Да; после импорта данные независимы | Автоматическая | Нужна правка кода; review; `snap connect`; при отказе — пустая колода |
| **F** | Classic confinement, свой app id | `~/.local/share/lurknotes/` (реальный) | Видны, используются на месте | Classic review (manual) | Да, если id разный; при одинаковом — конфликт | Не нужна | Меняет решение карты (strict); слабее изоляция; classic-review |
| **G** | Правка кода: `G_APPLICATION_NON_UNIQUE` + свой lock/socket single instance | Любой | Зависит | Нет `dbus`-review | Да | Зависит | Меняет продукт; ломает текущий механизм argv/хоткея; вне 0.1.0 |

**Вариант A** — единственный, который сохраняет strict, не требует `personal-files`, не конфликтует с deb/pipx и укладывается в «0.1.0 как есть» (меняется только переменная окружения и `snapcraft.yaml`). Он всё равно требует `dbus`-слот и manual review; это неизбежно для любого strict-варианта с `Gtk.Application`.

**Вариант D** — единственный **strict**-вариант, который даёт «старые заметки сразу, без копирования», но цена — super-privileged интерфейс, ручное подключение и общий файл с deb. Для 0.1.0 это перебор. (Classic, вариант F, тоже даёт старые данные сразу, но меняет confinement.)

**Вариант F** — fallback, если strict-сборка упрётся в X11/EWMH (тикет 02) или если Store не утвердит `dbus`-слот. Classic снимает и `personal-files`, и `dbus`-слот, но требует classic-review и меняет решение карты.

---

## 8. Рекомендация

Для 0.1.0:

1. **Strict + отдельный application id для snap** (`LURKNOTES_APP_ID` в `snapcraft.yaml`), например `dev.lurknotes.LurkNotesSnap` или `io.github.hoter.LurkNotes`. Код не менять.
2. **`dbus`-слот на то же имя** (`bus: session`), и сразу подать snap declaration / manual review. Это обязательное условие запуска, а не опция.
3. **Данные — в `SNAP_USER_DATA`** (дефолт кода): `~/snap/lurknotes/<rev>/.local/share/lurknotes/`. Если сборка не использует desktop-helper, явно зафиксировать `XDG_DATA_HOME=$SNAP_USER_DATA/.local/share` в `environment:`, чтобы унаследованный `XDG_DATA_HOME` не увёл приложение в недоступный реальный путь; с `gnome`-расширением helper и так ставит тот же путь (и перезаписывает унаследованное значение).
4. **`personal-files` не подключать.** Миграцию описать в README/листинге: скопировать `notes.json` в `~/snap/lurknotes/current/.local/share/lurknotes/`, убрать старый autostart, поправить хоткей/удалить старый пакет.
5. **Автозапуск — только через `snapcraft.yaml` `autostart:`**; `--install-autostart` для snap-пользователей не документировать (файл уйдёт в `SNAP_USER_DATA/.config`, который GNOME не читает).
6. **Проверить на живой сборке** (до `stable`):
   - `snap run lurknotes --version` без `dbus`-слота → ожидаем `Failed to register: ... AccessDenied` (подтверждает необходимость слота);
   - со слотом — `RequestName` и второй экземпляр `snap run lurknotes new` передаёт argv первому;
   - snap + deb одновременно: deb-first и snap-first (ожидаем: если deb запущен первым — snap падает; если snap первым — deb уходит в snap; это и есть причина разнести id);
   - `snap refresh` с запущенным приложением (refresh awareness) и без;
   - `snap revert` после правок в новой ревизии: убедиться, что заметки не откатываются (или задокументировать это);
   - `snap remove` → `snap saved` → переустановка → `snap restore`;
   - `snap remove --purge` (данные исчезают, snapshot нет).
7. **Открытый вопрос для тикета 05:** утвердит ли Store `dbus`-слот на `dev.lurknotes.*` без подтверждения владения доменом `lurknotes.dev`; если нет — брать `io.github.hoter.*` и указать GitHub как источник владения.

---

## 9. Неопределённости

- **Store review:** точное поведение при отсутствии snap declaration на `dbus`-слот (блокировка ревизии на manual review vs отказ в слоте) по документации не детализировано; проверять на первой загрузке. Для `personal-files` base declaration прямо `allow-installation: false`, там без declaration снап не установится.
- **`dev.lurknotes.*`:** принадлежность домена `lurknotes.dev` издателю не подтверждена; это может всплыть на ревью D-Bus имени.
- **Same-id конфликт:** вывод «snap падает, если deb уже запущен» следует из AppArmor-правил (у snap нет `dbus (send)` к чужому имени), но не проверен на двух реальных сборках LurkNotes. Проверить вручную.
- **`snap revert` и данные:** код пропускает `copy-snap-data` при revert, поэтому правки новой ревизии не переносятся; документация обещает обратное. Проверить на живой сборке и решить, нужен ли `SNAP_USER_COMMON` или предупреждение пользователю.
- **`XDG_DATA_HOME` и desktop-helper:** на `ktorrent` helper выставляет `$SNAP_USER_DATA/.local/share`; для `gnome`-расширения это тот же `desktop-exports`, но конкретная сборка LurkNotes ещё не существует. Проверить `snap run --shell lurknotes -c 'env | grep XDG'`.
- **`snap remove` snapshot:** по умолчанию включён на classic Ubuntu, но пользователь мог выставить `snapshots.automatic.retention=no`; в отчёте считаем дефолт.
- **`snap connect` и sudo:** документация показывает команду без sudo; в типичной системе подключение интерфейса — привилегированная операция. Проверить на целевой машине.
- **`SNAP_USER_COMMON`:** технически можно использовать для данных, общих между ревизиями (это решает и проблему revert), но `desktop-launch` перезаписывает `XDG_DATA_HOME`, а его theme/icon-подготовка рассчитана на `SNAP_USER_DATA`. Для 0.1.0 не рекомендуется; если понадобится — делать wrapper после command-chain и проверять theme lookup.

---

## 10. Источники

### Документация Canonical (snap-docs)

- Environment variables: <https://github.com/canonical/snap-docs/blob/main/docs/reference/development/environment-variables.md> — `HOME=$SNAP_USER_DATA`, `SNAP_USER_DATA`/`SNAP_USER_COMMON`, `SNAP_REAL_HOME`, `SNAP_APP_BUS_NAME`.
- Home interface: <https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/home-interface.md> — только не-скрытые файлы, auto-connect на classic.
- Personal files interface: <https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/personal-files-interface.md> — `$HOME/.local/share/foo`, approval, `snap connect`, auto-connect: no, super-privileged.
- Data locations: <https://github.com/canonical/snap-docs/blob/main/docs/reference/administration/data-locations.md> — удаление `~/snap` и `/var/snap`, snapshot ~30 дней, `--purge`.
- Create data snapshots: <https://github.com/canonical/snap-docs/blob/main/docs/how-to-guides/manage-snaps/create-data-snapshots.md> — что входит в snapshot, auto snapshot, 31 день, `snap restore`, `snap export-snapshot`, `snap forget`.
- Revisions: <https://github.com/canonical/snap-docs/blob/main/docs/explanation/how-snaps-work/revisions.md> — копирование `SNAP_USER_DATA` при переходе на новую ревизию, симлинк `current`.
- Refresh awareness: <https://github.com/canonical/snap-docs/blob/main/docs/explanation/how-snaps-work/refresh-awareness.md> — отложенный refresh при запущенном приложении.
- D-Bus interface: <https://github.com/canonical/snap-docs/blob/main/docs/reference/interfaces/dbus-interface.md> — `dbus`-слот, well-known name, snap declaration/manual review.

### Исходники snapd 2.77.1

- `snap/snapenv/snapenv.go` — `HOME`, `XDG_RUNTIME_DIR`, `SNAP_REAL_HOME`, experimental exposed-home: <https://github.com/canonical/snapd/blob/2.77.1/snap/snapenv/snapenv.go>
- `interfaces/builtin/home.go` — `owner @{HOME}/[^s.]**`, запрет скрытых каталогов: <https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/home.go>
- `interfaces/builtin/personal_files.go` — `allow-installation: false`, `deny-auto-connection: true`: <https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/personal_files.go>
- `interfaces/builtin/common_files.go` — разворачивание `$HOME` в `@{HOME}`, `owner`, создание каталогов: <https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/common_files.go>
- `interfaces/builtin/dbus.go` — `dbus (bind)`, `RequestName`, classic-only receive-from-unconfined: <https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/dbus.go>
- `overlord/snapstate/backend/snapdata.go` — копирование `SNAP_USER_DATA` при refresh: <https://github.com/canonical/snapd/blob/2.77.1/overlord/snapstate/backend/snapdata.go>
- `overlord/snapstate/snap.go` — `copy-snap-data` пропускается при `Flags.Revert`: <https://github.com/canonical/snapd/blob/2.77.1/overlord/snapstate/snap.go>
- `wrappers/internal/service_unit_gen.go` — `bus-name` → systemd `BusName=`: <https://github.com/canonical/snapd/blob/2.77.1/wrappers/internal/service_unit_gen.go>

### GLib

- `gio/gapplicationimpl-dbus.c` — `RequestName` с `DO_NOT_QUEUE`, обработка `EXISTS`/ошибки: <https://gitlab.gnome.org/GNOME/glib/-/blob/main/gio/gapplicationimpl-dbus.c>
- `gio/gapplication.c` — `Failed to register` и exit 1: <https://gitlab.gnome.org/GNOME/glib/-/blob/main/gio/gapplication.c>

### Python

- `os.path.expanduser` — `HOME` на Unix: <https://docs.python.org/3/library/os.path.html#os.path.expanduser>

### Живые пробы (эта машина, 2026-10-28)

- `snap run --shell glab` — `HOME=/home/dev/snap/glab/6906`, `XDG_DATA_HOME`/`XDG_CONFIG_HOME` unset.
- `snap run --shell ktorrent` — `XDG_DATA_HOME=/home/dev/snap/ktorrent/64/.local/share`, `XDG_CACHE_HOME=/home/dev/snap/ktorrent/common/.cache`.
- `snap run --shell glab -c 'cat /home/dev/.local/share/lurknotes/notes.json'` — `Permission denied`.
- `snap run --shell glab -c 'dbus-send ... RequestName ...'` — `org.freedesktop.DBus.Error.AccessDenied` с `label="snap.glab.glab (enforce)"`.
- `/var/lib/snapd/apparmor/profiles/snap.ktorrent.ktorrent` — `dbus (bind) name=org.kde.ktorrent`; `snap.yaml` `ktorrent` — `slots.session-dbus-interface interface: dbus, bus: session, name: org.kde.ktorrent`.
