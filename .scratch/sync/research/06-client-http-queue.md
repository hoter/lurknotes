# HTTP, офлайн-очередь, таймеры и токен в клиенте

Дата проверки: 2026-11-21.
Машина: Ubuntu 24.04.5, Python 3.12.3 (system и core24), PyGObject 3.48.2 на хосте.
Снапы на машине: `core24` 20260824 (rev 2124), `gnome-46-2404` (стабильный канал,
PyGObject 3.54.2), `mesa-2404`, `lurknotes` 0.1.0 (установлен из текущего
`snapcraft.yaml`; `snap list` показывает правку 13).

**Короткий вывод.**

- **HTTP: `http.client`/`urllib` из core24, без новых зависимостей.** TLS и
  CA-сертификаты уже в base, `requests` лежит в `usr/lib/python3/dist-packages`
  самого core24, но по умолчанию **не импортируется** и в снап не попадает.
  Интерфейс `network` — implicit-интерфейс snapd (проверено документацией и
  кодом snapd), но в профиль снапа он попадает только если объявлен в
  `snapcraft.yaml`; AppArmor-профиль установленного снапа сегодня *не* содержит
  ни одного правила `network inet`. Поэтому `snapcraft.yaml` меняется ровно на
  одну строку `plugs: [network]`, а не на новый part или пакеты. Рекомендация —
  `http.client` с явным `ssl.SSLContext`; `urllib` не нужен.
- **Приёмка:** проверка `probe_network` в `scripts/acceptance.py` уже валидна
  для выключенной синхронизации без изменений: приёмка ни разу не создаёт
  `sync.json`, а тумблер по умолчанию выключен — значит «0 AF_INET/AF_INET6»
  остаётся контрактом. Что нужно — так это не тащить сетевые импорты в старт
  процесса и добавить отдельную пробу «сеть включена» с мок-сервером.
- **Таймеры:** `timers.py` — только типы (`Schedule`/`Cancel`), `retry.py` —
  политика с одним таймером *на объект* и растущим до 30 с backoff. Для
  отправки очереди **не переиспользовать существующий `Retrier`**, а создать
  второй экземпляр того же класса и обёртку `scheduler` в `app.py`; блокирующий
  HTTP-вызов из `GLib.timeout_add` делать нельзя.
- **0600:** один путь `os.open(..., O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW, 0o600)`
  работает и в `$SNAP_USER_DATA/.local/share/lurknotes`, и в
  `~/.local/share/lurknotes`: `os.open` применяет `mode` только при создании,
  существующий файл поэтому надо пересоздавать через атомарную замену либо
  дополнять `os.fchmod`. Проверено на этой машине (0644 при обычном `open`,
  0600 при `os.open`).
- **Очередь:** паттерн `store.py` (tmp + `fsync` + `os.replace` + `fsync`
  каталога) переносится как есть и переживает `kill -9`; но в проекте нет ни
  одной точки, где этот паттерн вынесен в общую функцию. Ничего в `store.py`
  менять не обязательно, но лучше вынести два приватных хелпера или повторить
  ~20 строк в новом `queue.py`.

---

## Ответы

### 1. HTTP-клиент: что есть в core24 и в `gnome-46-2404`

**В core24 есть вся стандартная библиотека сети и TLS.**

Проверено на распакованном base, а не на памяти:

```
$ ls /snap/core24/current/usr/lib/python3.12/ | grep -E 'ssl|socket|http|urllib'
http  socket.py  socketserver.py  ssl.py  urllib
$ ls /snap/core24/current/usr/lib/python3.12/lib-dynload | grep -E '_ssl|_socket|_hashlib'
_hashlib.cpython-312-x86_64-linux-gnu.so  _socket...so  _ssl...so
$ ls /snap/core24/current/usr/lib/x86_64-linux-gnu | grep -E '^libssl|^libcrypto'
libcrypto.so.3  libssl.so.3
$ ls /snap/core24/current/etc/ssl/certs | wc -l
243
```

Интерпретатор base импортируется без всякой настройки вне снапа:

```
$ python3 -S -c 'import ssl'   # /snap/core24/current/usr/bin/python3.12
3.12.3 OpenSSL 3.0.13 30 Jan 2024
DefaultVerifyPaths(cafile='/usr/lib/ssl/cert.pem', capath='/usr/lib/ssl/certs', ...)
```

То есть `http.client`, `urllib.request` и `ssl` с системным trust store
работают в base «из коробки». Стандартная библиотека CPython это подтверждает:
[`http.client`](https://docs.python.org/3.12/library/http.client.html) —
«client side of the HTTP and HTTPS protocols… HTTPS support is only available if
Python was compiled with SSL support»; [`urllib.request`](https://docs.python.org/3.12/library/urllib.request.html)
использует `HTTP/1.1` и «includes `Connection:close` header in its HTTP requests».

**`requests` в core24 физически есть, но в `sys.path` не попадает.**

```
$ ls /snap/core24/current/usr/lib/python3/dist-packages | grep -iE 'requests|urllib3|idna'
idna  requests  requests-2.31.0.egg-info  urllib3  urllib3-2.0.7
$ python3 -S -c 'import sys; sys.path.append("/snap/core24/current/usr/lib/python3/dist-packages"); import requests, certifi'
requests 2.31.0 urllib3 2.0.7
certifi /etc/ssl/certs/ca-certificates.crt
```

Это пакеты Ubuntu-образа base (`cloud-init` тянет `requests`), но `python3` в base
запускается без `/usr/lib/python3/dist-packages` в пути (Debian-схема `python3.x`
+ `/usr/lib/python3/dist-packages` включается только через `sitecustomize` хоста,
которого в base нет — при `-S` список пути был
`['', '/usr/lib/python312.zip', '/usr/lib/python3.12', '/usr/lib/python3.12/lib-dynload']`).
Попытка импорта в чистом base без ручного `sys.path` даёт `ModuleNotFoundError:
No module named 'requests'`. Тем более нельзя на `requests` из base полагаться:
ревизия base меняется независимо от снапа.

**`gnome-46-2404` сетевых Python-пакетов не даёт.** В
`/snap/gnome-46-2404/current/usr/lib/python3/dist-packages` лежат `gi`, `cairo`,
`dbus`, `PyGObject`, `setuptools`, `pip`, `wheel`, `packaging` — и всё. Сеть
в платформе есть только на уровне библиотек (GLib `GNetworkMonitor`,
glib-networking с `libproxy`), но в Python-путь это не входит.

**Важно:** `gnome-46-2404` — *content snap*, и его код не попадает внутрь
`.snap`. Копия исходников в снапе — это `cp -a $CRAFT_PART_SRC` (только
`src/lurkn`), а `desktop-launch` лишь добавляет к `PYTHONPATH`
`$SNAP_DESKTOP_RUNTIME/usr/lib/python3.12` и `.../python3/dist-packages`
(`/snap/gnome-46-2404/current/command-chain/desktop-launch`, строки ~626–630;
каталога `python3.12/site-packages` в платформе нет). Значит **импортировать
`requests` внутри снапа в принципе нельзя**, не добавив его в prime.

**Расширение `gnome` для core24** подключает только content-интерфейсы
(`gnome-46-2404`, `gpu-2404`, темы) и app-plugs `desktop`, `desktop-legacy`,
`gsettings`, `opengl`, `wayland`, `x11` — среди них нет ни `network`, ни
`network-bind` ([GNOME extension, Snapcraft docs](https://documentation.ubuntu.com/snapcraft/stable/reference/extensions/gnome-extension/)).

**Можно ли обойтись без новых зависимостей — да, но с одной строкой в
`snapcraft.yaml`.**

- `network` в snapd — **implicit**-интерфейс на уровне объявления слота
  (слот `allow-installation: slot-snap-type: [core]`), описание — «Can access
  the network as a client» (`interfaces/builtin/network.go`, `networkSummary`),
  т.е. слот каждому приложению предоставляет сам base; `network-bind` нужен
  только серверу. При этом *правила* в профиль приложения попадают только
  когда приложение объявляет plug `network` (`networkConnectedPlugAppArmor`
  содержит инструкцию `#include <abstractions/nameservice>`,
  `/run/systemd/resolve/stub-resolv.conf rk,`, `@{PROC}/sys/net/... r` и
  `#include <abstractions/ssl_certs>` — без этого нет ни резолва имён, ни прав
  на сокеты).
- Проверка по живому профилю текущего снапа:
  `grep -nE 'network (inet|netlink)' /var/lib/snapd/apparmor/profiles/snap.lurknotes.lurknotes`
  → только `network netlink raw,` из `desktop-legacy` (строка 1467). Правил
  `network inet`/`inet6` нет — а seccomp `socket AF_INET` при этом пропускает
  (см. ниже), поэтому на уровне sandbox единственная защита от исходящего
  TCP сегодня — отсутствие правил AppArmor. Вывод: при добавлении HTTP
  `snapcraft.yaml` должен явно объявить `network`. Для `network`
  auto-connection штатная — это не `personal-files`, поэтому «ручного шага» в
  Store нет, но появление нового plug'а в проверке ревью стоит отметить.
- seccomp снапа `socket AF_INET`/`AF_INET6` **разрешает** для всех приложений;
  фильтрация AF_* отдана AppArmor — см. комментарий «we can allow 'socket' for
  all domains except AF_NETLINK and let AppArmor handle the rest»
  ([`interfaces/seccomp/template.go`](https://github.com/canonical/snapd/blob/master/interfaces/seccomp/template.go)).
  То есть seccomp сам сетевой сокет не запрещает; ограничение живёт в AppArmor
  и появляется только когда объявлен plug `network`. Поэтому «ноль сокетов при
  выключенном тумблере» проверяет именно то, что код не открывает сокет, а не
  что sandbox его не пустит — это и есть смысл приёмочной проверки.

**Рекомендация по клиенту.** Для трёх эндпоинтов (login, push, pull) зависимость
не нужна вообще. Предпочтительный вариант — `http.client` с явным контекстом,
потому что можно отключить прокси-автоопределение, редиректы и не тянуть
`urllib.request`:

```python
import http.client, ssl

CONTEXT = ssl.create_default_context()   # /etc/ssl/certs внутри base
conn = http.client.HTTPSConnection(host, 443, timeout=10, context=CONTEXT)
conn.request("POST", "/api/notes", body=payload, headers={...})
resp = conn.getresponse()
```

`urllib.request` как альтернатива: он поддерживает `timeout` и `context`, но
«if proxy settings are detected… `ProxyHandler` is default installed»
([urllib.request docs](https://docs.python.org/3.12/library/urllib.request.html)),
а прокси-настройки в strict-снапе приходят от `desktop`-плага через
glib-networking — лишний источник запросов не в тот хост. `http.client` этого
не делает.

Если когда-нибудь всё же понадобится `requests`, путь ровно один: скопировать его
из `usr/lib/python3/dist-packages` core24 в `$CRAFT_PART_INSTALL/site-packages`
(`requests`, `urllib3`, `idna`; `certifi` не нужен — `requests` умеет системные
CA) и дописать `$SNAP/site-packages` в `sys.path` обёртки `bin/lurknotes`.
По размерам это десятки файлов и несколько мегабайт в снапе ради трёх
эндпоинтов — лишнее.

**Что поменять:** `snapcraft.yaml` — добавить `plugs: [network]` к app
(единая строка, без нового part'а, без `stage-packages`); `__main__.py` —
ничего (импорт HTTP-модулей только внутри `sync`-модуля, см. §2); точка
входа `bin/lurknotes` в `snapcraft.yaml` — ничего, `urllib`/`http.client` уже
в base.

### 2. «Нет сетевых сокетов»: что проверяет приёмка сейчас и что делать

Проверка — `probe_network` в `scripts/acceptance.py` (раздел 9, строки
1131–1231). Она запускает обычное приложение с `--autostart`, ждёт полоску,
спит 1.5 с и собирает **три независимых наблюдения**:

1. **inodes сокетов процесса** — обход `/proc/<pid>/fd` и разбор ссылок
   `socket:[N]` (`socket_inodes`, строки 1134–1145);
2. **пересечение этих inode-ов с таблицами ядра** — `/proc/net/tcp`, `tcp6`,
   `udp`, `udp6` (inode — 10-е поле) (`net_table`, строки 1148–1159 и
   `probe_network`, строки 1189–1198);
3. **`lsof -nP -p <pid> -a -i`** — второй, независимый инструмент: любая строка
   вывода, кроме строк с `lsof:`, считается провалом (строки 1199–1224).

Условия провала буквально:

```python
if inet_hits:                                   # есть живые AF_INET/AF_INET6 сокеты?
    raise AcceptanceFailure(f"network sockets open: {inet_hits}")
if lsof_lines:
    raise AcceptanceFailure(f"lsof lists internet sockets: {lsof.stdout.strip()}")
```

AF_UNIX-сокеты считаются и печатаются, но не являются провалом: «6 AF_UNIX
(D-Bus expected)» — это единственные сокеты v1
(`.scratch/lurknotes-mvp/acceptance.md`, раздел «Network»).
Метрика не смотрит на DNS-запросы, на CLOSE-сокеты в TIME_WAIT и на UDP к
`systemd-resolved` — только на живые inode-ы процесса и `lsof`.

**Почему проверка остаётся валидной при выключенной синхронизации — без правок.**
`probe_network` кладёт данные в свежий `XDG_DATA_HOME` и никогда не создаёт
`sync.json` (`env_for`, строки 99–120). Синхронизация по решению 4.4/5.2
включается только явным тумблером и живёт в `sync.json`; значит все пробы
приёмки работают в состоянии «выключено», и требование спеки §11 «Ноль сетевых
запросов, пока синхронизация выключена»
(`.scratch/edge-notes/spec.md`, строка 312) остаётся ровно тем же контрактом.
Именно это зафиксировал тикет 08: «Критерий «нет сети» остаётся в §11 и
работает как контракт для выключенного тумблера» (issue 08, «Почему не менял»).

**Что могло бы сломать проверку** (и как это не допустить):

- **сетевой сокет, созданный при старте, до чтения `sync.json`** — например
  DNS-резолв адреса сервера, `GNetworkMonitor`, `Gio.NetworkMonitor`-подписка.
  Тогда `probe_network` упадёт на «честном» приложении. Правило: ни одного
  обращения к `socket`/`Gio.NetworkMonitor` на пути `do_startup`/`do_activate`;
  `http.client` импортируется лениво внутри первого `flush()`, и только если
  `sync.json` прочитан и `enabled: true`.
- **сетевые импорты на старте** — импорт `ssl` сам по себе сокет не создаёт,
  поэтому проверку не сломает, но импорт `http.client` в `app.py` удлиняет
  холодный старт (цель — медиана 1500 мс, `COLD_TARGET_MS`) и делает «сеть
  всегда загружена» правдой. Держать
  импорт в `sync.py`, а `sync.py` подгружать через `importlib`/локальный
  `import` только при включённом тумблере.
- **`GNetworkMonitor`/`Gio.NetworkMonitor` из GLib** — glib-networking уже в
  `LD_LIBRARY_PATH` (`desktop-launch`); подписка на сетевые события тянет
  netlink-сокеты в главный процесс и даёт D-Bus-канал к
  `org.freedesktop.portal.ProxyResolver`. Ни то, ни другое не нужно: очередь
  проверяется по своему таймеру, а ошибки сети — по исключениям HTTP-клиента.

**Что добавить, когда синхронизация включается** — отдельная проба,
`probe_network_enabled`: поднять в `acceptance.py` локальный
`http.server.ThreadingHTTPServer` на `127.0.0.1:<port>` (стандартная библиотека;
это часть приёмочного стенда, не снапа), записать `sync.json` с
`enabled: true` и `server: "http://127.0.0.1:<port>"`, включить тумблер,
дождаться одного push и **утверждать обратное**:

- в `inet_hits` есть **ровно один** inode, и он совпадает с портом мок-сервера
  (`/proc/net/tcp` даёт `0100007F:<port hex>` — можно сверить адрес и порт, а не
  только факт);
- после выключения тумблера и `time.sleep(1)` `inet_hits` снова пуст, а новый
  `probe_network` проходит;
- `lsof` показывает только адрес `127.0.0.1:<port>`, никаких других хостов
  (в частности, нет `:53` UDP).

Для проверки в **strict-снапе** этот же сценарий работает как есть: `network`
профиль даёт доступ и к loopback, и к внешним адресам, поэтому единственный
способ поймать «пошли не туда» — сверять адрес и порт в `/proc/net/tcp`, а не
только факт соединения.

### 3. Таймеры и ретраи: подходят ли `timers.py` и `retry.py`

**`timers.py`** — это только протокол: `Handle`, `Schedule = Callable[[int,
Callable[[], None]], Handle]`, `Cancel`. В нём нет ни одного таймера; он
специально не зависит от GLib (докстринг: «The pure state machines… never import
GLib», `timers.py:1–7`). Для очереди он «подходит» ровно в той мере, в какой
нужен тип: отдельного механизма он не даёт.

**`retry.py`** — политика с важной особенностью:

```python
RETRY_DELAYS_MS = (1000, 2000, 5000, 15000, 30000)
...
def failed(self) -> None:
    if self._handle is not None:      # ровно один таймер на объект
        return
    delay = self._delays[min(self._failures, len(self._delays) - 1)]
    self._failures += 1
    self._handle = self._schedule(delay, self._fire)

def _fire(self) -> None:
    self._handle = None               # «attempt is expected to call failed() or succeeded()»
    self._attempt()
```

(см. `src/lurkn/retry.py:15–62` и тесты `tests/test_retry.py` — в том числе
`test_a_failed_save_schedules_one_bounded_retry` и
`test_backoff_grows_and_stops_at_the_last_delay`). Он уже используется так:

```python
self._retrier = Retrier(self._retry_save, schedule=GLib.timeout_add,
                        cancel=GLib.source_remove)        # app.py:124–128
```

а `_save_notes` вызывает `self._retrier.failed()`/`succeeded()`
(`app.py:339–366`), `do_shutdown` — `self._retrier.stop()` (`app.py:264`).

**Годится ли он для очереди:** да, при трёх оговорках.

1. **Нужен второй экземпляр, не общий.** `Retrier` хранит *один* `_handle` и
   один счётчик `_failures`; если передать его же в очередь, `failed()` сетевой
   ошибки задержит ретрай сохранения на диске (и наоборот). Создавать
   `Retrier(self._sync_after_failure, schedule=..., cancel=...)` отдельно от
   `_retrier`.
2. **`schedule=GLib.timeout_add` подойдёт только если отправка не блокирует
   главный цикл.** `GLib.timeout_add` вызывает callback из main loop
   ([PyGObject/GLib: `GLib.timeout_add`](https://docs.gtk.org/glib/func.timeout_add.html));
   блокирующий `http.client` с `timeout=10` внутри него остановит hover/undo/
   редактор на время запроса. Два чистых варианта:
   - **отдельный поток**: `threading.Thread(target=flush, daemon=False)`, внутри
     `timeout` у сокета (`http.client.HTTPSConnection(timeout=…)`, «blocking
     operations (like connection attempts) will timeout after that many
     seconds»), результат — `GLib.idle_add` обратно в main loop. В `do_shutdown`
     — `Event.set()` + `join(timeout=…)`, как требует документация threading:
     «Daemon threads are abruptly stopped at shutdown… use a suitable signalling
     mechanism such as an `Event`»
     ([threading docs](https://docs.python.org/3.12/library/threading.html));
   - **`Gio`-источник вместо `GLib.timeout_add`**: в стеке уже есть
     `Gio.SocketClient` (в Gio typelib) и `libsoup`/`webkit2gtk` из layout расширения — нативный async без Python-
     потока, но добавляет `GLib.MainContext`-API, сигналы и ещё одну
     зависимость; для трёх эндпоинтов это больше кода, чем поток.
3. **Повтор «раз в N минут» — это второй таймер, отдельно от backoff.**
   `Retrier` сбрасывает счётчик при `succeeded()`, но после успешной отправки
   остаётся pull раз в N минут и «досылка при старте». Это не `Retrier`, а
   отдельный `GLib.timeout_add_seconds(N*60, …)`, который держится в
   `app.sync` и отменяется в `do_shutdown`/при выключении тумблера (по образцу
   `_cancel_save_timer`, `app.py:998–1001`).

**Конкретная рекомендация.** Не менять `retry.py` и `timers.py`; в `app.py`
завести `self._sync` (объект `SyncSender`, создаётся лениво при первом
включении тумблера, обнуляется при выключении) и `self._sync_retrier`.
`SyncSender.flush()` вызывается из фонового потока, по завершении —
`GLib.idle_add(self._on_sync_result, ok)`; `_on_sync_result` делает
`self._sync_retrier.failed()` или `.succeeded()` и обновляет иконку состояния.
Поток не стартовать, пока `sync.json` отсутствует или `enabled == false`.
`GLib.timeout_add` остаётся главным источником для периодического pull и
переиспользуется только тогда, когда хочется «проверить, есть ли очередь» без
блокирующей работы.

**Свойство, которое надо сохранить:** `retry.py` полагается на то, что
сработавший таймер «scheduler has already removed its source» (`retry.py:58–61`)
и поэтому не отменяет handle после срабатывания. `GLib.timeout_add` этому
соответствует (source удаляется, когда callback вернул `False`/
`GLib.SOURCE_REMOVE`). Обёртка очереди вокруг планировщика обязана вернуть
`GLib.SOURCE_REMOVE`, как это уже делает `app._schedule_timer`
(`app.py:163–168`).

### 4. Права 0600 для файла токена в снапе и в deb, одним путём

**Факты, на которых это стоит.**

- В strict-снапе `HOME` = `$SNAP_USER_DATA` (решение research 03), а
  `store.default_path()` использует `$XDG_DATA_HOME`, который `desktop-launch`
  выставляет в `$SNAP_USER_DATA/.local/share`; в deb/pipx — обычный
  `~/.local/share`. Значит **один и тот же путь
  `<data>/lurknotes/sync.json` и `<data>/lurknotes/token`**, а различается
  только `$HOME`.
- Права каталога `~/snap/<name>/<rev>/.local/share` создаются snapd (не
  мировые); в deb каталог создаёт `mkdir(parents=True)`, который подчиняется
  umask — под типичным `022` он будет 0755. Поэтому `0600` настраивается на
  самом файле токена, а не наследуется от родителя. Дополнительно `0700` на
  `lurknotes/` можно поставить явно — но `mkdir(mode=…)` тоже фильтруется
  umask («Where it is used, the current umask value is first masked out»,
  [`os.mkdir`](https://docs.python.org/3.12/library/os.html#os.mkdir)), так что
  для строгости нужен отдельный `os.chmod(dir, 0o700)`. Существующий
  `notes.json` уже лежит в каталоге `0755` — менять это не обязательно: токен
  защищён своими правами.
- `os.open(path, flags, mode)` применяет mode **только при создании файла**:
  «Open the file *path* and set various flags according to *flags* and possibly
  its mode according to *mode*. When computing *mode*, the current umask value
  is first masked out» ([os.open, CPython 3.12](https://docs.python.org/3.12/library/os.html#os.open)).
  При повторном открытии существующего файла никакой mode не применяется —
  проверено:

  ```
  normal open() under umask 022: 0o644
  os.open(..., 0o600) first create: 0o600
  reopen existing with 0o600:     0o600   (unchanged, not forced)
  ```

  Отсюда два следствия: (а) если файл уже был создан с 0644 (например, прежней
  версией/пользователем), `os.open` его не «исправит» — нужен `os.fchmod`;
  (б) при атомарной замене временный файл создаётся с 0600, и `os.replace`
  переносит на целевое имя его inode вместе с правами — проверено: после
  `replace` файл остаётся `0o600` (см. §5).

**Один путь для обеих упаковок** — новый модуль `src/lurkn/secrets.py`
(дерево одно, `snapcraft.yaml` копирует `src/lurkn` целиком):

```python
import os, stat
from pathlib import Path

def _write(path: Path, data: bytes) -> None:
    path.parent.parent.mkdir(parents=True, exist_ok=True)   # lurknotes/
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                      | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.fchmod(fd, 0o600)        # принудительно, даже если tmp уже был
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)           # атомарно: имя и inode заменяются вместе
    _fsync_dir(path.parent)
```

Плюсы по сравнению с `path.open("w")`: `O_NOFOLLOW` не даёт подменить
существующий файл симлинком (стандартный `open` следует по ссылке; `os.path`
предупреждает, что он «does not perform any kind of symbolic link checking»),
`O_CLOEXEC` (в Python 3.4+ не наследуемый по умолчанию — `open` docs: «The
newly created file is *non-inheritable*»), `fchmod` выправляет уже
существующий файл с неверными правами, `fsync` + `replace` переживает `kill -9`.
`O_NOFOLLOW` и `O_CLOEXEC` доступны: на этой машине `hasattr(os, "O_NOFOLLOW")`
= True.

**Тест**, который надо добавить рядом с существующими в `tests/test_store.py`
(там уже есть `skipif(os.geteuid() == 0, reason="root ignores directory
permissions")`): `secrets.write_token(...)` → `stat.S_IMODE(...) == 0o600`,
повторная запись поверх файла `0644` → снова `0600`, симлинк вместо файла →
`OSError`. Подменять `SNAP_USER_DATA` не нужно: путь строится от
`default_path()`, а `XDG_DATA_HOME` тесты уже подменяют (`test_store.py:598`).

**Что поменять:** `sync.json` на токен **не** влияет — хранить токен отдельным
файлом `token` рядом с `sync.json` (одно решение 4.4 «токен — файл 0600, без
libsecret»); `store.py` не меняется; сама функция — в новом `secrets.py`.

### 5. Офлайн-очередь и `kill -9`: переносится ли паттерн `store.py`

**Что именно делает `store.py`** (`src/lurkn/store.py:313–404`, раздел
«writing»):

1. `payload` → `json.dumps(...)`;
2. `parent.mkdir(parents=True, exist_ok=True)`;
3. открыть `self.tmp_path` на запись, `write`, `flush`, `os.fsync(handle.fileno())`;
4. (если идёт восстановление) скопировать текущий файл в бэкап через временное
   имя и `os.rename` — тоже best effort;
5. `os.replace(self.tmp_path, self.path)` — атомарная подмена в рамках одной
   ФС;
6. `_fsync_directory()` — `os.open(parent, O_RDONLY)` + `os.fsync`, чтобы
   rename стал durable («Make the rename durable; fsync on a directory is not
   portable»);
7. при `BaseException` — удалить временные, не трогая main и backup.

Это ровно «atomic replace» (см. `rename(2)`: новый файл появляется в каталоге
одним шагом); последовательность **переживает SIGKILL**, потому что SIGKILL
не прерывает уже начатый `write`/`rename` на середине — после `kill -9`
возможны только «старый файл целиком» или «новый файл целиком», а `.tmp`
остаётся мусором, который следующий save перезаписывает (приёмочный
`probe_kill_stress` подтверждает это на 15 прогонах: «every notes.json parsed
coherently», `.scratch/lurknotes-mvp/acceptance.md», раздел про `kill -9`).
То, что `fsync` перед `replace` обязателен, а `fsync` каталога делает durable
сам rename, — та же логика, что в `store.py:398–404`. **Да, паттерн
переносится на очередь как есть.**

**Что конкретно нужно для очереди, чтобы `kill -9` не терял изменения:**

1. **Записать в очередь ДО отправки, а не после.** Поток-отправщик берёт
   элемент из очереди, отправляет, и только после `2xx` удаляет его (или
   отмечает `acked`). Если процесс убьют между отправкой и удалением —
   элемент остаётся и уйдёт повторно; сервер должен быть идемпотентным по
   клиентскому UUID (это уже заложено в модели: `id` — UUID4 на клиенте,
   решение 2.1 карты; «последняя запись побеждает» 3.1 делает повторный push
   безопасным). Обратный порядок («удалили, потом отправили») как раз теряет
   изменения при `kill -9`.
2. **Атомарная замена файла очереди** — тот же tmp + `fsync` + `os.replace` +
   `fsync(dir)`. Один файл `queue.json` на `sync.json`-каталог
   (`<data>/lurknotes/queue.json`), формат
   `{"version": 1, "items": [...]}`, `version` — чтобы будущее поле не
   сломало старую версию (как в `store.py:VERSION = 1`).
3. **`fsync` содержимого файла обязателен до `replace`** — иначе на ext4 с
   `data=ordered` после сбоя питания/ядра (для `kill -9` одного этого мало, но
   паттерн пишется один раз) `rename` может стать виден раньше данных.
   `store.py` делает правильную последовательность: `fsync(tmp)` → `replace` →
   `fsync(dir)`; хелпер `_fsync_directory` копируется без изменений.
4. **Безопасный «добавить в очередь» под гонкой.** Очередь пишут из main loop
   (сохранение заметки) и читает/переписывает поток. Нужен
   `threading.Lock` вокруг read-modify-write, или отправка только через
   `queue.Queue` и один writer. `kill -9` снимает вопрос «недописанная
   память» (её нет), но не вопрос «два писателя одновременно» — его решает
   lock, а не atomic replace.
5. **Удаление элемента из очереди** — тоже через полную атомарную перезапись
   (`полуочередь без элемента` → tmp → replace). Нельзя `truncate` файл на
   месте.
6. **Первый запуск после `kill -9`:** `queue.json` может отсутствовать (тогда
   пустая очередь), `.tmp` рядом — мусор, игнорируется/удаляется перед
   первой записью (ровно как `store.py` делает `leftover.unlink()` в
   `except BaseException` — но при `kill -9` этот except не выполнится, так что
   **удалять `.tmp` ещё и при старте** до первой записи).
7. **Чего уже хватает в коде:** `Store._fsync_directory` — единственный
   нужный примитив (строки 398–404), и `autostart.install` повторяет тот же
   паттерн с `chmod` и своим `_fsync_directory` (`autostart.py:98–126`) — то
   есть паттерн уже знаком команде в двух местах. Стоит вынести общий
   `atomic_write(path, data, mode=0o600, fsync_dir=True)` в `lurkn/atomic.py`
   (новый модуль) и перевести на него `store.save`, `autostart.install` и
   `secrets.write`; но это не требуется для корректности — допустимо повторить
   ~20 строк в `queue.py`.

**Проверено локально:** `Store(path)` на **ещё не существующем** подкаталоге
(`/tmp/opencode/sparse/lurknotes/notes.bak.json`) сохраняет успешно — родитель
создаётся на строке 334. Значит путь
`Store(Path(default_path()).with_name("queue.json"))` тоже сработает и в
первый запуск.

**Что менять:** новый `src/lurkn/queue.py` (чтение/запись/append/ack с тем же
паттерном), вызов из `app.py` в `_save_notes` **после** удачного `store.save`
(чтобы не ставить в очередь заметку, которую не удалось сохранить локально
— иначе при перезапуске в очереди может быть заметка, которой нет на диске), и
`do_shutdown` — дать потоку дописать очередь, но не дать сохранить текст мимо
очереди (сейчас `do_shutdown` вызывает `_shutdown_deck` → `_save_notes`).

**Риск, который надо записать в спеку:** `kill -9` между `store.save` и
`queue.append` теряет одно изменение из очереди, хотя сама заметка на диске
есть. Поэтому либо обе записи делать подряд и сразу (окно — микросекунды), либо
при старте сверять `notes.json` с очередью: если в файле есть заметка без
элемента в очереди и синхронизация включена — досылать её целиком (это
проще, состояние и так придёт с pull).

---

## Что конкретно поменять (сводка)

| Файл | Изменение |
|---|---|
| `snapcraft.yaml` | к `apps.lurknotes` добавить `plugs: [network]`; ничего больше (ни part'ов, ни `stage-packages`, ни `PYTHONPATH`) |
| `src/lurkn/sync.py` (новый) | HTTP-клиент на `http.client` + `ssl.create_default_context()`, `SyncSender` с фоновым потоком и `GLib.idle_add`, ленивый импорт |
| `src/lurkn/queue.py` (новый) | `queue.json` на диске, атомарная запись тем же паттерном, что `store.py` |
| `src/lurkn/secrets.py` (новый) | файл `token` с `os.open(..., 0o600 | O_NOFOLLOW)` + `fchmod` + `fsync` + `replace` |
| `src/lurkn/app.py` | второй `Retrier` для сети, периодический `GLib.timeout_add_seconds`, старт/стоп потока по тумблеру, вызов `queue.append` после `store.save`, `stop()` в `do_shutdown` |
| `src/lurkn/timers.py`, `retry.py`, `store.py` | не менять (по желанию — вынести `atomic_write` в общий модуль) |
| `scripts/acceptance.py` | `probe_network` не менять; добавить `probe_network_enabled` с мок-сервером на `127.0.0.1` |
| `src/lurkn/__main__.py` | не менять (сетевые импорты не должны быть в пути холодного старта) |

---

## Источники

### Первичные (документация, код snapd, документация CPython)

- Snapcraft, GNOME extension (core24 pulls `gnome-46-2404` + `gpu-2404`;
  app plugs `desktop`, `desktop-legacy`, `gsettings`, `opengl`, `wayland`,
  `x11` — без `network`):
  <https://documentation.ubuntu.com/snapcraft/stable/reference/extensions/gnome-extension/>
- snapd, `interfaces/builtin/network.go` — слот на `core`, «Can access the
  network as a client»; правила профиля — только при объявленном plug'е:
  <https://github.com/canonical/snapd/blob/master/interfaces/builtin/network.go>
- snapd, `interfaces/seccomp/template.go` — `socket AF_INET`/`AF_INET6`
  разрешены всем, медиация AF_* — AppArmor:
  <https://github.com/canonical/snapd/blob/master/interfaces/seccomp/template.go>
- CPython 3.12, `http.client`:
  <https://docs.python.org/3.12/library/http.client.html>
- CPython 3.12, `urllib.request` (default `ProxyHandler` при наличии
  `*_proxy`, `Connection: close`):
  <https://docs.python.org/3.12/library/urllib.request.html>
- CPython 3.12, `os.open` (mode применяется при создании, umask, non-inheritable
  fd) и `os.makedirs`/`umask`:
  <https://docs.python.org/3.12/library/os.html#os.open>
- CPython 3.12, встроенная `open` (opener, non-inheritable):
  <https://docs.python.org/3.12/library/functions.html#open>
- CPython 3.12, `socket` (timeouts, `socket.timeout` = `TimeoutError`):
  <https://docs.python.org/3.12/library/socket.html>
- CPython 3.12, `threading` (daemon threads and shutdown, `Event`, `Lock`,
  `Condition`):
  <https://docs.python.org/3.12/library/threading.html>
- GLib, `g_timeout_add` (callback из main loop):
  <https://docs.gtk.org/glib/func.timeout_add.html>

### Код и данные на этой машине (воспроизводимо)

- Состав core24: `/snap/core24/current/usr/lib/python3.12/{http,urllib,ssl.py,socket.py,lib-dynload/_ssl*}`
  и `/snap/core24/current/usr/lib/python3/dist-packages/{requests,urllib3,idna}`.
- Импорт base: `/snap/core24/current/usr/bin/python3.12 -S -c 'import ssl'` и
  `... -S -c 'import requests'` (последнее — `ModuleNotFoundError` без
  `sys.path.append`).
- `gnome-46-2404`: `ls /snap/gnome-46-2404/current/usr/lib/python3/dist-packages`
  (нет `requests`), `command-chain/desktop-launch` строки ~626–630.
- Профиль AppArmor текущего снапа:
  `grep -nE 'network (inet|netlink)' /var/lib/snapd/apparmor/profiles/snap.lurknotes.lurknotes`
  → одна строка `network netlink raw,` из `desktop-legacy`.
- Права файла: `os.open(..., 0o600)` при umask 022 даёт 0600, обычный
  `open()` — 0644; `os.replace` проносит права tmp-файла.
- `Store.save` на несуществующем подкаталоге — успешно.

### Код проекта

- `src/lurkn/store.py:313–404` — атомарная запись и `_fsync_directory`.
- `src/lurkn/retry.py:15–62` — `Retrier`, один таймер, backoff до 30 с.
- `src/lurkn/timers.py:1–19` — только протокол `Schedule`/`Cancel`.
- `src/lurkn/app.py:124–128, 163–171, 255–303, 339–371, 998–1001` — создание
  `Retrier`, мост к `GLib.timeout_add`, `do_shutdown`, save/retry, debounce.
- `src/lurkn/autostart.py:81–126` — тот же паттерн записи + `chmod` +
  `_fsync_directory`.
- `scripts/acceptance.py:99–120, 1131–1231` — `env_for` (свежий
  `XDG_DATA_HOME`, без `sync.json`) и `probe_network`.
- `.scratch/lurknotes-mvp/acceptance.md` («Network») — 6 AF_UNIX, 0
  AF_INET/AF_INET6, `lsof` пуст.
- `.scratch/edge-notes/spec.md:11, 33, 312–314` — «без сети, пока тумблер
  выключен», записи только в `$XDG_DATA_HOME`.
- `.scratch/sync/map.md`, «Decisions so far» (2.1–2.3, 3.1–3.2, 4.4, 5.x) и
  `issues/08-task-spec-v11.md`, «Почему не менял».
- `.scratch/snap-store/issues/03-research-data-and-instance.md` — `HOME =
  $SNAP_USER_DATA`, `XDG_DATA_HOME` под снапом.
