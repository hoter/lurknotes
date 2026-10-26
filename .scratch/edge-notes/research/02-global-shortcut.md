# Глобальные горячие клавиши и единый экземпляр на GNOME 46

Дата проверки: 2026-10-26.
Машина: Ubuntu 24.04.5, Wayland, GNOME Shell 46.0, GTK 4.14.5, PyGObject 3.48.2, GLib 2.80.0.

**Короткий вывод.** На этой машине портала `org.freedesktop.portal.GlobalShortcuts` нет:
`xdg-desktop-portal-gnome` 46.2 его не реализует, а в апстриме бэкенд появился только в
GNOME 48. Единственный поддерживаемый путь в v1 — ручная привязка в GNOME Settings →
Keyboard → Custom Shortcuts на CLI-команду. Команда должна попадать в уже запущенный
экземпляр через `GApplication` (D-Bus, `HANDLES_COMMAND_LINE`), а фокус окна на Wayland
не гарантирован: его даёт только compositor по валидному `xdg-activation` токену.

---

## Ответы

### 1. Поддерживает ли `xdg-desktop-portal-gnome` 46 портал GlobalShortcuts?

**Нет. Ни на этой машине, ни в апстриме для ветки 46.**

Что установлено:

```
ii  xdg-desktop-portal          1.18.4-1ubuntu2.24.04.3
ii  xdg-desktop-portal-gnome    46.2-0ubuntu1
ii  xdg-desktop-portal-gtk      1.15.1-1build2
```

Что реально отвечает шина (команда из тикета):

```
$ gdbus introspect --session --dest org.freedesktop.portal.Desktop \
    --object-path /org/freedesktop/portal/desktop
```

На объекте `/org/freedesktop/portal/desktop` экспортировано 28 интерфейсов
(`Inhibit`, `Background`, `Location`, `Notification`, `Screenshot`, `Account`,
`NetworkMonitor`, `Print`, `Settings`, `GameMode`, `RemoteDesktop`, `MemoryMonitor`,
`OpenURI`, `Realtime`, `Secret`, `WebExtensions`, `Wallpaper`, `Camera`,
`InputCapture`, `Device`, `PowerProfileMonitor`, `DynamicLauncher`, `ScreenCast`,
`Clipboard`, `Email`, `Trash`, `ProxyResolver`, `FileChooser`).
`org.freedesktop.portal.GlobalShortcuts` среди них **нет** — ни интерфейса, ни его
методов `CreateSession` / `BindShortcuts` / `ListShortcuts`.

Это подтверждается ещё тремя независимыми проверками:

1. Файл бэкенда, который читает frontend:

   ```
   $ cat /usr/share/xdg-desktop-portal/portals/gnome.portal
   [portal]
   DBusName=org.freedesktop.impl.portal.desktop.gnome
   Interfaces=org.freedesktop.impl.portal.Access;...;org.freedesktop.impl.portal.Wallpaper;
   UseIn=gnome
   ```

   В списке `Interfaces` нет `org.freedesktop.impl.portal.GlobalShortcuts`.
   У `gtk.portal` его тоже нет.

2. В бинарнике бэкенда нет даже строки с именем портала:

   ```
   $ strings /usr/libexec/xdg-desktop-portal-gnome | grep -ic GlobalShortcuts
   0
   ```

3. Службы портала при этом живы — дело не в том, что портал не запущен:

   ```
   $ systemctl --user list-units 'xdg-desktop-portal*'
   xdg-desktop-portal.service        active running
   xdg-desktop-portal-gnome.service  active running
   xdg-desktop-portal-gtk.service    active running
   ```

**Когда портал появился.**

- Frontend (сам `xdg-desktop-portal`) умеет GlobalShortcuts с версии **1.16.0**
  (2022-12-12): «Introduce the Global Shortcuts portal» — [NEWS xdg-desktop-portal].
  На машине 1.18.4, то есть frontend его знает.
- Бэкенд GNOME получил его только в **GNOME 48**: в `NEWS` пакета
  `xdg-desktop-portal-gnome` запись `Changes in 48.rc — Add global shortcuts portal
  backend` — [NEWS xdg-desktop-portal-gnome]. В 47.x такой записи нет.
- GNOME 48 release notes: «Global shortcuts: apps can now create their own
  system-wide shortcuts… Apps must request permission to add global shortcuts, and
  global shortcuts can be removed from the Apps page in the Settings app» —
  [GNOME 48 release notes].
- Дополнительно: `xdg-desktop-portal-gnome` 48.alpha требует
  `xdg-desktop-portal >= 1.19.1` — [NEWS, 48.alpha]. На Ubuntu 24.04 стоит 1.18.4,
  поэтому даже гипотетический бэкпорт одного бэкенда не заработал бы без более
  нового frontend.

Frontend экспортирует только те порталы, которые объявил выбранный бэкенд; раз
`gnome.portal` не содержит `GlobalShortcuts`, интерфейс и не появляется на шине.

**Итог:** на Ubuntu 24.04 / GNOME 46 портала нет и включить его без обновления
GNOME нельзя. Автоматическая регистрация хоткея через портал — не вариант для v1.

### 2. Если портала нет: ручная привязка в GNOME Settings

Точная инструкция — в разделе «Инструкция для человека» ниже. Кратко:

- Settings → Keyboard → «View and Customize Shortcuts» → «Custom Shortcuts» → «+».
- Name: `Edge Notes: New note`, Command:
  `/home/<user>/.local/bin/edge-notes new`, shortcut `Ctrl+Alt+N`.
- Вторая привязка: `Edge Notes: All notes` → `.../edge-notes all`, `Ctrl+Alt+A`.

Почему именно эти комбинации: на этой машине `Ctrl+Alt+N`, `Ctrl+Alt+A`,
`Ctrl+Alt+E` и `Ctrl+Alt+Space` не заняты ни одной схемой GSettings (проверено
перебором всех схем, 1939 записей). `Super+N` занят («Focus the active
notification»), `Super+A` — «Show all applications». Комбинации с `Super` лучше
не трогать: их разбирает shell.

**Ограничения такой привязки:**

- Она глобальна в пределах графической сессии: срабатывает независимо от того,
  какое окно в фокусе. Это то, что нужно.
- Рассчитана на активную графическую сессию; на экране блокировки и login-экране
  вводом владеет shell, и рассчитывать на неё там не стоит.
- Это одна строка команды. Нет shell-подстановок: `~`, `$HOME`, пайпы и редиректы
  не раскрываются. Нужен абсолютный путь к исполняемому файлу; если нужен shell —
  `sh -c '...'`.
- Приложение не может прочитать или изменить привязку. Она живёт в GSettings
  (`org.gnome.settings-daemon.plugins.media-keys custom-keybindings`) и управляется
  только человеком через Settings. Это осознанный компромисс v1.
- Конфликт не диагностируется приложением: если комбинацию уже занял другой
  глобальный шорткат, она просто не сработает (или сработает чужое действие).
  Проверять надо в том же списке Custom Shortcuts и в Pre-defined shortcuts.
- Команда запускается отсоединённо, без терминала: stdout/stderr никуда не видны.
  Для отладки — писать лог в файл.
- Для Flatpak в будущем команда будет `flatpak run <app-id> new`; сам Flatpak-пакет
  на GNOME 46 не может зарегистрировать глобальный хоткей (портала нет).
- Фокус окна после срабатывания не гарантирован — см. вопрос 5.

Проверить, что Settings реально записал:

```
$ gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']

$ gsettings list-recursively \
  'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/'
... binding '<Control><Alt>n'
... command '/home/dev/.local/bin/edge-notes new'
... name 'Edge Notes: New note'
```

### 3. Как CLI-вызов попадает в уже запущенный экземпляр

Механика `GApplication` (GTK4 `Gtk.Application` — подкласс):

- Приложение с `application_id` занимает well-known имя на session bus. Второй
  процесс с тем же ID не становится primary: он отправляет вызов по D-Bus и
  завершается. Это и есть single instance — [GApplication docs].
- Чтобы различать `new` и `all`, нужен флаг
  `Gio.ApplicationFlags.HANDLES_COMMAND_LINE` (значение 8). Тогда argv доставляется
  в primary, в сигнал `command-line` / vfunc `do_command_line`, а не теряется в
  `Activate`. Без флага второй запуск приходит как обычная активация без аргументов
  — [ApplicationFlags], [GApplication docs].
- `Gio.ApplicationFlags.NON_UNIQUE` (32) делает ровно обратное — не использовать.
- `Gio.ApplicationFlags.IS_SERVICE` (1) — режим сервиса: ждёт активацию до 10 секунд;
  полезен, если приложение должно жить в фоне и не показывать окно на старте.

Минимальная схема на Python:

```python
import sys, gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib

APP_ID = "io.github.edgenotes.EdgeNotes"   # имя .desktop = APP_ID + ".desktop"

class App(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.win = None
        self.editor = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        command = args[0] if args else "toggle"

        token = None
        data = cmdline.get_platform_data()
        if data is not None:
            v = data.lookup_value("activation-token", GLib.VariantType.new("s"))
            if v is not None:
                token = v.get_string()

        self.show_panel(command, token)
        return 0

    def show_panel(self, command, token):
        # ... создать/показать панель, выбрать заметку ...
        if token:
            self.win.set_startup_id(token)   # до present(), см. вопрос 5
        self.win.present()
        self.editor.grab_focus()
```

Что здесь важно:

- `do_command_line` вызывается и в primary при локальном первом запуске, и в
  primary при удалённом вызове. Второй процесс при этом уже завершился.
- `cmdline.get_platform_data()` — это `a{sv}`; GTK-клиент уже положил туда
  `activation-token`, если процесс был запущен из сессии с токеном
  (см. вопрос 5 и [GTK 4.14.5 `gtkapplication.c`]).
- `do_activate` при `HANDLES_COMMAND_LINE` не используется; дефолтное поведение
  (показать окно) надо реализовать в `do_command_line` для пустого argv.

**`gapplication action`.** Это альтернативный вход: `gapplication action
<APP_ID> new` вызывает `org.freedesktop.Application.ActivateAction` и активирует
экспортированный `GAction` — [man gapplication], [Desktop Entry spec, D-Bus
Activation]. Условия:

- приложение должно экспортировать `GAction` с таким именем
  (`Gio.SimpleAction` + `app.add_action`);
- если приложение ещё не запущено, D-Bus должен уметь его запустить: нужен
  `.desktop` с `DBusActivatable=true`, названный `<APP_ID>.desktop`, и
  D-Bus service-файл с `Exec=` (иначе `gapplication action` просто не найдёт имя);
- платформенные данные (включая activation-token) при action-вызове приходят в
  `before_emit`, а не в обработчик действия, поэтому пробрасывать токен в окно
  сложнее, чем через `do_command_line`.

Для хоткея проще и надёжнее не использовать `action`, а запускать сам бинарник:
`edge-notes new`. Если приложение уже работает, GApplication отправит argv в primary
и выйдет; если нет — этот же процесс станет primary и обработает argv локально.
Ни `.desktop`, ни D-Bus service-файл для этого не обязательны (они понадобятся
позже для интеграции с шеллом и для `DBusActivatable`).

**Чтобы «не запускался второй экземпляр»** достаточно:

1. один стабильный `application_id`;
2. `Gio.ApplicationFlags.HANDLES_COMMAND_LINE`;
3. обработка argv в primary;
4. не вызывать `quit()` при закрытии панели — иначе следующее нажатие будет
   холодным стартом. Либо `Gtk.Window.set_hide_on_close(True)`, либо `app.hold()`,
   либо автозапуск (вопрос 4).

Холодный старт Python + GTK занимает заметное время; с автозапуском и скрытой
панелью хоткей будет ощущаться мгновенным.

### 4. Autostart через `~/.config/autostart/*.desktop`

Спецификация: каталог `$XDG_CONFIG_HOME/autostart` (обычно
`~/.config/autostart`), файлы в формате Desktop Entry, запускаются при логине в
графическую сессию — [Autostart spec]. GNOME читает его через `gnome-session`;
в man-странице перечислены `$XDG_CONFIG_HOME/autostart`,
`$XDG_CONFIG_DIRS/autostart` и `/usr/share/gnome/autostart` — [man gnome-session].

На этой машине каталога ещё нет:

```
$ ls -la ~/.config/autostart
ls: невозможно получить доступ: Нет такого файла или каталога
```

Пример `~/.config/autostart/edge-notes.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Edge Notes
Comment=Edge notes deck
Exec=/home/dev/.local/bin/edge-notes --autostart
Icon=edge-notes
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
```

Поведение:

- Файл в `~/.config/autostart` имеет приоритет над одноимённым файлом в
  `/etc/xdg/autostart` — [Autostart spec].
- `Hidden=true` отключает запись (спецификация); GNOME дополнительно понимает
  `X-GNOME-Autostart-enabled=false` — это видно и в исходниках `gnome-session`
  (`GSM_APP_ENABLED_KEY`), и в строках установленного
  `/usr/libexec/gnome-session-binary`.
- `OnlyShowIn=GNOME;` / `NotShowIn=` ограничивают DE; `TryExec=` проверяет
  наличие бинарника — [Autostart spec].
- `X-GNOME-Autostart-Phase` (например, `Application`) задаёт фазу запуска;
  без ключа используется `Application` — [gnome-session,
  `gsm-autostart-app.c`]. Для панели это то, что нужно: не лезть в фазу
  WindowManager/Panel.
- `X-GNOME-AutoRestart=true` перезапускает упавший процесс; по умолчанию выключено.
- Запись появляется в «Startup Applications» (`gnome-session-properties`), и
  человек может выключить её галочкой.
- На Wayland автозапуск ничем не отличается от X11: процесс стартует внутри
  пользовательской сессии, `WAYLAND_DISPLAY` уже выставлен. Приложение не должно
  на старте показывать окно и пытаться взять фокус — это раздражает и всё равно
  может быть отклонено compositor'ом.

Для v1 автозапуск — оптимальный способ держать панель резидентной: хоткей тогда
только показывает уже существующее окно. Если автозапуск не нужен, первый вызов
после логина будет холодным стартом.

### 5. Может ли приложение на Wayland поднять окно и забрать фокус из фона?

**Не безусловно. На Wayland нет клиентского API «забрать фокус»: решает
compositor.** Штатный механизм — протокол `xdg-activation` — [xdg-activation-v1
protocol]:

1. Клиент, инициирующий активацию (лаунчер, shell, другое приложение), просит у
   compositor'а activation token.
2. Токен передаётся целевому клиенту отдельным каналом: через
   `XDG_ACTIVATION_TOKEN` в окружении дочернего процесса или через поле
   `activation-token` в platform data D-Bus-вызова
   `org.freedesktop.Application` — [Desktop Entry spec, D-Bus Activation].
3. Целевой клиент вызывает `xdg_activation_v1.activate(token, surface)`.
4. Compositor «can use this token to decide how to react»; он вправе отказать.
   Токен может быть недействителен уже в момент выдачи, например при focus
   stealing prevention — [xdg-activation-v1 protocol].

Что делает Mutter (проверено по тегу 46.0; в `main` логика та же, файл
`meta-wayland-activation.c`):

- токен принимается, только если у него есть `seat`, `surface` и валидный
  serial/surface, полученный из недавнего ввода
  (`token_can_activate()`);
- если токен валиден — `meta_window_activate_full()` (окно поднимается и
  получает фокус);
- если нет — `meta_window_set_demands_attention()`: окно поднимается/помечается
  как urgent, но **фокус клавиатуры не забирает** — [Mutter
  `meta-wayland-activation.c`].

Что делает GTK4 4.14:

- `GtkApplication` при отправке командной строки кладёт токен в platform data
  (`activation-token`), читая его из `XDG_ACTIVATION_TOKEN` /
  `DESKTOP_STARTUP_ID` — [GTK `gtkapplication.c`], [GDK `gdk.c`].
- `GdkToplevel.focus()` на Wayland: если есть startup id — вызывает
  `xdg_activation_v1_activate()` с ним; если нет — сам создаёт токен, привязывая
  его к **текущей сфокусированной поверхности этого клиента** и последнему serial
  — [GDK `gdktoplevel-wayland.c`].
- `gtk_window_present()` лишь «may mean … giving it the keyboard focus (possibly
  dependent on the user's platform, window manager and preferences)» —
  [Gtk.Window.present docs]. Гарантии фокуса нет.
- `gtk_window_set_startup_id()` надо вызывать **до** `present()`: GDK при
  установке id сразу вызывает `xdg_activation_v1_activate()`, а при map
  применяет сохранённый id — [Gtk.Window.set_startup_id docs], [GTK
  `gtkwindow.c`].

Практический вывод для Edge Notes:

- Если процесс запущен из GNOME (хоткей, лаунчер) и получил токен, его надо
  явно прочитать из platform data и поставить окну через
  `win.set_startup_id(token)` перед `present()`. Тогда шанс на фокус максимален.
- Через `xdg-activation` фоновый процесс без валидного токена фокус не получит:
  Mutter поднимет окно и поставит urgent. Отдельно есть обычная политика фокуса
  при первом map: свежесозданное окно может получить фокус и без токена, но для
  уже показанного окна это не работает — в Mutter автофокус делается только при
  `showing_for_first_time` — [Mutter `window.c`]. Полагаться на это нельзя.
- Токен, который создаёт лаунчер (gsd-media-keys), тоже может оказаться без
  `surface`, если у самого лаунчера нет сфокусированной поверхности; тогда
  `token_can_activate()` его отклонит. Это надо проверить на живой машине, а не
  считать гарантией.
- Поэтому UX не должен зависеть от фокуса: панель показывается у края, а
  `GtkTextView` получает фокус внутри окна, когда окно реально становится
  активным. Надёжный приём — подписаться на `notify::is-active` / `focus-in` и
  там вызывать `editor.grab_focus()`. Если compositor фокус не дал, человек
  кликает по панели один раз — клик всегда даёт фокус.
- Если 01 остановится на layer-shell: на GNOME/Mutter `zwlr_layer_shell_v1`
  нет, поэтому «клавиатурная интерактивность layer-shell» здесь неприменима;
  в этом тикете рассматривается обычное `Gtk.Window`. Для layer-shell на
  wlroots-композиторах фокус регулируется `keyboard_interactivity`, но это не
  наш случай.

### 6. Альтернативы без расширения GNOME Shell

| Вариант | Работает на GNOME 46 / Wayland? | Цена |
|---|---|---|
| GNOME Settings → Custom Shortcuts → CLI | Да, поддерживаемый путь | Ручная настройка; см. ограничения выше |
| `org.freedesktop.portal.GlobalShortcuts` | Нет; появился в GNOME 48 | На 46 недоступен; на 48+ требует app ID и разрешения |
| Расширение GNOME Shell | Да | Явно вне области карты |
| `keyd` с `command(...)` | Да, но это системный демон | Root; команда выполняется от root, GUI-приложение запускать неудобно; глобально на все раскладки/сессии |
| `interception-tools` / `evsieve` | Да, на уровне evdev | Root, свой демон, сложнее keyd |
| `sxhkd`, `xbindkeys` | Нет | Это X11-инструменты (`XGrabKey`); под Wayland глобальные клавиши так не ловятся |
| Приватный интерфейс `ShellKeyGrabber` (им пользуется gsd-media-keys) | Есть внутри shell | Не публичный API, версионно-зависимый; не использовать |

Почему так мало вариантов: в Wayland нет клиентского протокола глобального
перехвата клавиш. GNOME решает это либо через собственный shell (расширения,
приватный `ShellKeyGrabber` для gsd), либо через портал GlobalShortcuts, которого
на 46 нет. Поэтому «без расширения» остаётся ровно один нормальный путь —
Custom Shortcuts, который внутри и есть gsd-media-keys + shell grab, но
настраивается человеком.

`keyd` умеет `command(<shell command>)`, но выполняет её от пользователя,
запустившего демон (обычно root) — [keyd man page]. Для запуска GUI-приложения
это требует `runuser`/`sudo -u` с проброшенным окружением и выглядит хрупко.

---

## Инструкция для человека

### Шаг 0. Сделать исполняемую команду

Пусть приложение лежит в `/home/dev/projects/ubuntu/edge-notes/` (подставить
реальный путь). Создать обёртку без sudo:

```sh
mkdir -p ~/.local/bin
cat > ~/.local/bin/edge-notes <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /home/dev/projects/ubuntu/edge-notes/edge_notes.py "$@"
EOF
chmod +x ~/.local/bin/edge-notes
```

Проверить в терминале:

```sh
~/.local/bin/edge-notes new
```

Окно должно появиться. Второй запуск в другом терминале не должен создавать
второе приложение — только показать панель.

> Если `~/.local/bin` не в `PATH`, это не важно: в Settings указывается
> абсолютный путь.

### Шаг 1. Открыть настройки

1. Открыть Activities, набрать `Settings`, открыть **Settings**.
2. Слева выбрать **Keyboard**.
3. В разделе **Keyboard Shortcuts** нажать **View and Customize Shortcuts**.
4. Выбрать **Custom Shortcuts**.
5. Нажать **+** (или **Add Shortcut**, если список пуст).

(Это ровно тот путь, который описывает справка GNOME — [GNOME Help, Set keyboard
shortcuts].)

### Шаг 2. Привязать «новую заметку»

- **Name:** `Edge Notes: New note`
- **Command:** `/home/dev/.local/bin/edge-notes new`
- Нажать **Set Shortcut…** и нажать **Ctrl+Alt+N**.
- **Add**.

### Шаг 3. Привязать «все заметки»

Повторить «+»:

- **Name:** `Edge Notes: All notes`
- **Command:** `/home/dev/.local/bin/edge-notes all`
- Shortcut: **Ctrl+Alt+A**.

### Шаг 4. Проверить

```sh
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
```

Ожидается массив из двух object path (`custom0`, `custom1`). Затем нажать
`Ctrl+Alt+N` из любого приложения — панель должна появиться.

Если не срабатывает:

1. Запустить ту же команду в терминале — проверить, что дело не в приложении.
2. Открыть Custom Shortcuts и проверить, что комбинация не занята другим
   действием (в списке Pre-defined shortcuts тоже).
3. Проверить, что в Command нет `~` и `$HOME` — только абсолютный путь.
4. Посмотреть лог приложения (stdout из шортката никуда не попадает; писать в
   файл).
5. Убедиться, что приложение действительно single-instance: в логе не должно
   быть двух стартов.

### Шаг 5 (по желанию). Автозапуск

```sh
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/edge-notes.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Edge Notes
Comment=Edge notes deck
Exec=/home/dev/.local/bin/edge-notes --autostart
Icon=edge-notes
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
```

Приложение при `--autostart` должно стартовать скрыто (панель не показывает,
фокус не трогает). Выключить автозапуск можно либо `Hidden=true` в этом файле,
либо галочкой в **Startup Applications**, либо `X-GNOME-Autostart-enabled=false`.

### Что остаётся решить человеку

- Финальный `application_id` и имя `.desktop` (они должны совпадать:
  `<APP_ID>.desktop`), например `io.github.edgenotes.EdgeNotes`.
- Комбинации: `Ctrl+Alt+N` / `Ctrl+Alt+A` или более редкие
  `Ctrl+Alt+Shift+N` / `Ctrl+Alt+Shift+A`.
- Нужен ли автозапуск в v1 (резидентная панель и мгновенный хоткей) или
  допустим холодный старт.
- Поведение, когда Mutter отказал в фокусе: показывать панель с urgent-флагом и
  ждать клика или дополнительно давать звуковой/визуальный сигнал.
- Добавлять ли позже ветку через GlobalShortcuts для GNOME 48+ (сейчас — нет).

---

## Источники

**Портал GlobalShortcuts**

- Спецификация интерфейса: <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html>
- `xdg-desktop-portal` NEWS, 1.16.0 (портал представлен):
  <https://github.com/flatpak/xdg-desktop-portal/blob/main/NEWS.md>
- `xdg-desktop-portal-gnome` NEWS (48.rc: «Add global shortcuts portal backend»;
  48.alpha: зависимость от xdg-desktop-portal >= 1.19.1):
  <https://gitlab.gnome.org/GNOME/xdg-desktop-portal-gnome/-/blob/main/NEWS>
  (зеркало: <https://github.com/GNOME/xdg-desktop-portal-gnome/blob/main/NEWS>)
- GNOME 48 release notes, «Global shortcuts»:
  <https://release.gnome.org/48/>
- Локальные проверки: `dpkg -l 'xdg-desktop-portal*'`,
  `gdbus introspect --session --dest org.freedesktop.portal.Desktop --object-path
  /org/freedesktop/portal/desktop`,
  `/usr/share/xdg-desktop-portal/portals/gnome.portal`,
  `strings /usr/libexec/xdg-desktop-portal-gnome`,
  `systemctl --user list-units 'xdg-desktop-portal*'`.

**GNOME Custom Shortcuts**

- GNOME Help, «Set keyboard shortcuts» (Custom Shortcuts):
  <https://help.gnome.org/users/gnome-help/stable/keyboard-shortcuts-set.html>
- Схемы GSettings: `org.gnome.settings-daemon.plugins.media-keys`
  (`custom-keybindings`) и
  `org.gnome.settings-daemon.plugins.media-keys.custom-keybinding`
  (`name`, `command`, `binding`); проверено через `gsettings list-recursively`.
- Реализация запуска команд: `gnome-settings-daemon`,
  `plugins/media-keys/gsd-media-keys-manager.c` (`execute()`, `launch_app()`,
  `gdk_display_get_app_launch_context()`, `g_app_info_launch()`):
  <https://github.com/GNOME/gnome-settings-daemon/blob/46.0/plugins/media-keys/gsd-media-keys-manager.c>

**GApplication / single instance**

- `Gio.Application` (process uniqueness, D-Bus, actions):
  <https://docs.gtk.org/gio/class.Application.html>
- `Gio.ApplicationFlags` (`HANDLES_COMMAND_LINE`, `IS_SERVICE`, `NON_UNIQUE`):
  <https://docs.gtk.org/gio/flags.ApplicationFlags.html>
- `man gapplication` (локально): `gapplication action <APP-ID> <ACTION>
  [PARAMETER]`, `gapplication launch`.
- Desktop Entry Specification, «D-Bus Activation» (интерфейс
  `org.freedesktop.Application`, имя `.desktop` = app ID, поля platform data
  `desktop-startup-id` и `activation-token`):
  <https://specifications.freedesktop.org/desktop-entry-spec/latest/dbus.html>
- Исходники GLib: `gio/gdesktopappinfo.c` (выставляет `DESKTOP_STARTUP_ID` и
  `XDG_ACTIVATION_TOKEN` дочернему процессу и кладёт `activation-token` в
  platform data при D-Bus-активации):
  <https://github.com/GNOME/glib/blob/main/gio/gdesktopappinfo.c>
- Исходники GLib: `gio/gapplication-tool.c` (`gapplication action` / `launch`
  пересылают `XDG_ACTIVATION_TOKEN` как `activation-token` в platform data):
  <https://github.com/GNOME/glib/blob/main/gio/gapplication-tool.c>

**Autostart**

- Desktop Application Autostart Specification:
  <https://specifications.freedesktop.org/autostart-spec/latest/>
- `man gnome-session` (локально): каталоги `$XDG_CONFIG_HOME/autostart`,
  `$XDG_CONFIG_DIRS/autostart`, `/usr/share/gnome/autostart`;
  `gnome-session-properties`.
- `gnome-session`, `gnome-session/gsm-autostart-app.c` (ключи
  `X-GNOME-Autostart-*`, фазы):
  <https://github.com/GNOME/gnome-session/blob/46.0/gnome-session/gsm-autostart-app.c>
- Локально: `strings /usr/libexec/gnome-session-binary` содержит
  `X-GNOME-Autostart-enabled`, `X-GNOME-Autostart-Phase`,
  `X-GNOME-Autostart-Delay`, `X-GNOME-AutoRestart`, `AutostartCondition`.

**Wayland focus / xdg-activation**

- `xdg-activation-v1` protocol:
  <https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/xdg-activation/xdg-activation-v1.xml>
  (зеркало: <https://github.com/wayland-mirror/wayland-protocols/blob/main/staging/xdg-activation/xdg-activation-v1.xml>)
- Mutter, `src/wayland/meta-wayland-activation.c` (`token_can_activate()`,
  `meta_window_activate_full()`, `meta_window_set_demands_attention()`):
  <https://github.com/GNOME/mutter/blob/main/src/wayland/meta-wayland-activation.c>
- Mutter, `src/core/window.c` (автофокус только при `showing_for_first_time`,
  `intervening_user_event_occurred()`):
  <https://github.com/GNOME/mutter/blob/main/src/core/window.c>
- GTK 4.14.5, `gtk/gtkapplication.c` (`gtk_application_add_platform_data()` —
  кладёт `activation-token`):
  <https://github.com/GNOME/gtk/blob/4.14.5/gtk/gtkapplication.c>
- GTK 4.14.5, `gdk/gdk.c`
  (`gdk_get_startup_notification_id()` читает `XDG_ACTIVATION_TOKEN`, затем
  `DESKTOP_STARTUP_ID`):
  <https://github.com/GNOME/gtk/blob/4.14.5/gdk/gdk.c>
- GTK 4.14.5, `gdk/wayland/gdktoplevel-wayland.c`
  (`gdk_wayland_toplevel_set_startup_id()` → `xdg_activation_v1_activate()`;
  `gdk_wayland_toplevel_focus()`):
  <https://github.com/GNOME/gtk/blob/4.14.5/gdk/wayland/gdktoplevel-wayland.c>
- GTK 4.14.5, `gdk/wayland/gdkapplaunchcontext-wayland.c`
  (создание activation token для дочернего процесса):
  <https://github.com/GNOME/gtk/blob/4.14.5/gdk/wayland/gdkapplaunchcontext-wayland.c>
- GTK 4.14.5, `gtk/gtkwindow.c` (`gtk_window_notify_startup()`,
  `gtk_window_present_toplevel()`):
  <https://github.com/GNOME/gtk/blob/4.14.5/gtk/gtkwindow.c>
- Документация GTK: `Gtk.Window.present`,
  `Gtk.Window.set_startup_id`, `Gdk.Toplevel.focus`:
  <https://docs.gtk.org/gtk4/method.Window.present.html>,
  <https://docs.gtk.org/gtk4/method.Window.set_startup_id.html>,
  <https://docs.gtk.org/gdk4/method.Toplevel.focus.html>

**Альтернативы**

- keyd, man page (`command(<shell command>)`, выполняется от пользователя
  демона):
  <https://github.com/rvaiya/keyd/blob/master/docs/keyd.scdoc>
