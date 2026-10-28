# Публикация strict GUI-снапа в Snap Store: аккаунт, листинг, ревью, сборка

**Дата проверки:** 2026-10-28.
**Окружение:** Ubuntu 24.04, GNOME 46, x86_64, snapd 2.77.1, `snapcraft` не установлен, сеть есть.
**Метод:** документация Snapcraft/Snap, исходники snapd 2.77.1, исходники server-side
review-tools (Launchpad, commit `8368bbd`, 2026-10-26), исходники snapcraft.io
(форма листинга), публичный Snap Store API и локальный snapd. Аккаунта в Store нет,
поэтому шаги, требующие логина/загрузки, не выполнялись — это отмечено в разделе
«Неопределённости».

---

## Краткий вердикт

1. **Регистрация имени — отдельное ручное ревью.** С 2024 года любая заявка на новое
   имя снапа проходит проверку командой Store; целевой срок — 2 рабочих дня
   ([policy: Manual review of all new snap name registrations](https://forum.snapcraft.io/t/manual-review-of-all-new-snap-name-registrations/39440)).
   Это первое узкое место, а не загрузка файла.
2. **`x11`, `desktop` и `autostart` сами по себе ручное ревью не триггерят.** `x11` и
   `desktop` авто-подключаются; `autostart` вообще не проверяется review-tools, кроме
   схемы snap.yaml.
3. **Скрытые триггеры для этого приложения:** слот `dbus` с именем (вероятно нужен
   `Gtk.Application` для single-instance), атрибут `desktop-file-ids` у `desktop`,
   `personal-files`/`system-files` (например, для миграции из deb/pipx), `home` с
   `read: all`, `classic`. Все они дают `(NEEDS REVIEW)` в review-tools.
4. **`autostart:` в snapcraft.yaml — только объявление.** Файл `.desktop` должен
   положить в `$SNAP_USER_DATA/.config/autostart/` сам снап. Сейчас LurkNotes пишет
   его только по `--install-autostart`, поэтому при отказе от этого флага автозапуск
   в snap-сборке не заработает без изменения кода/обёртки.
5. **Сборка без root возможна** через LXD (пользователь в группе `lxd`), Multipass или
   `snapcraft remote-build`. `--destructive-mode` для core22+ требует root.
6. **Публикация:** `edge` → тест → `stable`. Ревизии неизменяемы; откат — повторный
   `snapcraft release` старой ревизии в канал (на клиенте — `snap revert`).
7. **Листинг:** title, summary, description, category, website, contact, license, icon,
   screenshots. Поля **keywords в текущей форме нет**; категория — слаг `utilities`,
   не `Utility`. Обновления листинга появляются сразу, без ревью.

---

## 1. Аккаунт, соглашение, регистрация имени

### 1.1 Аккаунт

Аккаунт Snap Store — это Ubuntu One; если его нет, Store предложит создать
([Snap Store Terms §3](https://canonical.com/legal/terms-and-policies/snap-store-terms),
[Register a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/register-a-snap/)).
Вход из терминала:

```bash
snapcraft login
```

Команда спрашивает e-mail, пароль Ubuntu One и, если включена, второй фактор
([Register a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/register-a-snap/)).
2FA не обязательна для публикации, но рекомендуется: без неё украденный пароль даёт
доступ к публикации от вашего имени. Включить её можно в настройках аккаунта
[Ubuntu One](https://login.ubuntu.com); после этого `snapcraft login` будет
запрашивать код.

### 1.2 «Publisher Agreement»

Страница, которую принимают при первом входе в качестве издателя, сейчас называется
**Developer Programme Agreement**; она состоит из двух документов — Snap Store Terms of
Service и Privacy Notice ([шаблон страницы](https://github.com/canonical/snapcraft.io/blob/master/templates/publisher/developer_programme_agreement.html),
[живая страница](https://snapcraft.io/account/agreement)). Старое название
«Publisher Agreement» — легаси; в тикете 06 его стоит переименовать.

Что важно из Terms для публикации:

- издатель вправе публиковать снапы после принятия Terms и создания аккаунта (§4.1);
- нельзя публиковать контент, нарушающий чужие права, закон, содержащий вредоносный код
  и т.п. (§5);
- Canonical может удалить снап из Store в любой момент (§4.3);
- издатель обязан включить применимую лицензию в снап и указать её в информации о снапе
  (§6.2) — это и есть основание считать поле `license` обязательным, даже если форма
  листинга не помечает его звёздочкой.

### 1.3 Имя `lurknotes`

Правила имени ([Register a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/register-a-snap/)):

- до 40 символов;
- только строчные латинские буквы, цифры и дефис;
- хотя бы одна буква;
- не начинается и не заканчивается дефисом;
- имя глобально уникально среди публичных и приватных Store и **не меняется после
  регистрации**.

`lurknotes` подходит. На 2026-10-28 публичный API не знает такого снапа
(`GET https://api.snapcraft.io/v2/snaps/info/lurknotes` → `404 resource-not-found`),
то есть имя не занято опубликованным снапом. Это не гарантия, что имя не
зарезервировано: окончательный ответ даёт только регистрация.

### 1.4 Ручное ревью имени

С марта 2024 действует политика: **каждая заявка на новое имя проходит ручную
проверку** ([policy post](https://forum.snapcraft.io/t/manual-review-of-all-new-snap-name-registrations/39440)).
Нужно указать имя и краткий комментарий о назначении снапа; команда Store проверяет,
нет ли признаков вредоносного/криптокошелькового ПО, и может запросить уточнения.
Целевой срок ответа — **2 рабочих дня**. При отказе имя не выдаётся; при подозрении
на вредоносность заявка отклоняется. На практике очередь бывает дольше: в форуме
есть случай, когда имя ждало одобрения около месяца
([Voiceflow-cli](https://forum.snapcraft.io/t/voiceflow-cli-snap-name/44511)).

Практический вывод: регистрировать имя нужно **до** сборки/загрузки и закладывать
2+ рабочих дня. Веб-форма `https://dashboard.snapcraft.io/register-snap/` позволяет
оставить комментарий о назначении; CLI `snapcraft register` комментарий не спрашивает
(в коде команды есть только подтверждение и вызов Store API —
[`snapcraft/commands/names.py`](https://github.com/canonical/snapcraft/blob/main/snapcraft/commands/names.py)),
поэтому для первой заявки лучше веб-форма.

CLI-путь (если регистрируете через CLI; заявка всё равно уходит на проверку):

```bash
snapcraft login
snapcraft whoami
snapcraft register lurknotes
snapcraft names
```

`snapcraft register` без `--yes` задаёт вопрос, действительно ли большинство
пользователей ожидает это ПО именно от вас; `--yes` пропускает подтверждение.
`snapcraft names` показывает зарегистрированные имена, дату и видимость.

---

## 2. Листинг: поля, лимиты, где что задаётся

Источник формы — `templates/publisher/listing.html` и `webapp/publisher/snaps/listing_views.py`
в репозитории snapcraft.io (master на 2026-10-28). Живая страница —
`https://snapcraft.io/<snap>/listing` после регистрации.

### 2.1 Поля

| Поле | Где задаётся | Обязательность | Лимиты/формат |
|---|---|---|---|
| Title | snapcraft.yaml `title` + веб-форма | форма: `required` | ≤ 40 символов |
| Summary | snapcraft.yaml `summary` + форма | форма: `required` | snapcraft.yaml ≤ 78; форма ≤ 128 |
| Description | snapcraft.yaml `description` + форма | форма: `required` | Markdown: bold, URL, списки, italics, code |
| Category | только веб-форма | не `required`, но рекомендуется | до 2 категорий; слаги из Store API |
| Developer website | snapcraft.yaml `website` + форма | нет | http(s), ≤ 256 |
| Contact | snapcraft.yaml `contact` + форма | нет | http(s) или e-mail, ≤ 256 |
| License | snapcraft.yaml `license` + форма | форма: нет; Terms §6.2: да | SPDX 2.1, напр. `MIT` |
| Icon | snapcraft.yaml `icon` + загрузка в форме | нет, но нужен для GUI-фронтов | 40×40–512×512, 1:1, ≤ 256 KB, PNG/JPEG/SVG |
| Screenshots | только веб-форма | нет | до 5; 480×480–3840×2160; 1:2–2:1; ≤ 2 MB; GIF/JPEG/PNG |
| Banner | только веб-форма | нет | 720×240–4320×1440, 3:1, ≤ 2 MB; нужен для «featured» |
| Video | только веб-форма | нет | Vimeo/YouTube/asciinema URL |
| Public metrics | только веб-форма | нет | чекбоксы популярности/карт |
| **Keywords** | — | — | **поля нет** |

Ограничения иконки/скриншотов/баннера взяты из актуального JS формы:
[`icon.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/icon.js),
[`media.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/media.js),
[`banner.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/banner.js).
Лимиты скриншотов совпадают с архивной doc-страницей
[Store listing and branding](https://forum.snapcraft.io/t/store-listing-and-branding/16397)
(она помечена как перенесённая в snapcraft.io/docs, но в текущем индексе документации
раздела про листинг нет).

### 2.2 Категория

Публичный API отдаёт 20 слагов:
`art-and-design`, `books-and-reference`, `development`, `devices-and-iot`, `education`,
`entertainment`, `featured`, `finance`, `games`, `health-and-fitness`, `music-and-audio`,
`news-and-weather`, `personalisation`, `photo-and-video`, `productivity`, `science`,
`security`, `server-and-cloud`, `social`, `utilities`
([Store API categories](https://api.snapcraft.io/v2/snaps/categories)).
Для LurkNotes правильный слаг — **`utilities`** (не `Utility`). В форме можно выбрать
вторую категорию; для заметок вторая, вероятно, не нужна.

### 2.3 Чего в форме нет

**Поля keywords нет** — ни в шаблоне, ни в JS, ни в backend-контексте
([`listing.html`](https://github.com/canonical/snapcraft.io/blob/master/templates/publisher/listing.html),
[`listing_views.py`](https://github.com/canonical/snapcraft.io/blob/master/webapp/publisher/snaps/listing_views.py)).
Если keywords уже попали в план тикета 07, их нужно убрать: поиск и
ранжирование в Store не настраиваются полем keywords. Влияют title, summary,
description, category и (для графических фронтов) иконка/скриншоты.

### 2.4 Где хранится листинг и как обновляется

- Форма: обновления листинга «appear immediately on the snap listing page» — то есть
  текст/медиа не блокируются ревью перед публикацией ([`listing.html`](https://github.com/canonical/snapcraft.io/blob/master/templates/publisher/listing.html)).
- `snap info lurknotes` показывает summary, license, contact, description, каналы;
  эти данные приходят из метаданных снапа/Store, поэтому расхождение с веб-формой
  надо проверять (локальная проверка: `snap info ktorrent` / `snap info firefox`).
- `snapcraft upload-metadata <snap>.snap` загружает из файла **summary, description,
  license, title и icon**; `--force` перезаписывает Store даже при конфликте
  ([код команды](https://github.com/canonical/snapcraft/blob/main/snapcraft/commands/upload.py);
  [doc](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/upload-metadata/)
  устарела и перечисляет только summary/description/icon). **Contact, website,
  category, screenshots, banner, video этим не загружаются** — только веб-форма.
- Обычный `snapcraft upload` не вызывает `upload-metadata`; метаданные из snap.yaml
  попадают в снап и отображаются в `snap info`, но ручные правки листинга могут
  перетираться при релизе (в контексте формы есть флаг `update_metadata_on_release`;
  поведение Store при загрузке новой ревизии стоит проверить на первом релизе).
  Практика: сначала загрузить ревизию, потом заполнить листинг в веб-форме и не
  запускать `upload-metadata --force` без необходимости.

### 2.5 Рекомендуемые значения для LurkNotes

- Title: `LurkNotes`.
- Summary: одна строка ≤ 78, без точки в конце (например, «Notes deck at the edge of
  your screen»; финальный текст — тикет 07).
- Description: Markdown, 1–2 абзаца + список возможностей; без обещаний Wayland-
  нативного края, которых нет.
- Category: `utilities`.
- Website: `https://github.com/<owner>/lurknotes` (точный URL — из README).
- Contact: `aytpaev@gmail.com` (форма принимает e-mail или URL).
- License: `MIT` (SPDX), и в snapcraft.yaml, и в форме; до публикации добавить файл
  `LICENSE` (в репозитории его пока нет — это отдельный пункт карты).
- Icon: 256×256 PNG, 1:1, < 256 KB, положить в `snap/gui/` и указать в `icon:`.
- Screenshots: 3–5 штук с реальным интерфейсом, Linux-скриншоты, 16:9 или ближе,
  минимум 480×480, без чужих платформ.

---

## 3. Что триггерит ручное ревью

### 3.1 Как устроено ревью

- После загрузки Store выполняет автоматическую проверку файла. Если ошибок нет,
  снап сразу становится доступен; если есть — snapcraft печатает summary и
  рекомендации, нужно исправить и загрузить новую ревизию
  ([Publish a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/publish-a-snap/)).
- Часть проверок помечена `manual_review=True`: это не «ошибка формата», а сигнал
  человеку. Ревизия не публикуется, пока ревьюер не снимет флаг
  ([review-tools, `sr_lint.py`](https://git.launchpad.net/review-tools/tree/reviewtools/reviews/sr_lint.py?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca),
  [`sr_declaration.py`](https://git.launchpad.net/review-tools/tree/reviewtools/reviews/sr_declaration.py?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca)).
- `review-tools` — тот же инструмент, который использует Store; его можно поставить
  локально как снап `review-tools` и проверить файл до загрузки
  (`snap info review-tools`: издатель Canonical, «used by the Ubuntu store»).

### 3.2 Таблица для интерфейсов LurkNotes

| Что | Ручное ревью? | Авто-connect | Источник/почему |
|---|---|---|---|
| `x11` | **Нет** (на classic) | да на classic | Базовая декларация ограничивает только слот; для plug ограничений нет. `x11` auto-connect: yes; на Ubuntu Core `deny-auto-connection`/`deny-connection` действуют, поэтому там поведение другое ([x11 interface](https://snapcraft.io/docs/reference/interfaces/x11-interface), [snapd `x11.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/x11.go#L37-L48)) |
| `desktop` (без атрибутов) | **Нет** | да | `allow-installation` требует, чтобы `desktop-file-ids` отсутствовал; без атрибута всё разрешено ([`desktop.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/desktop.go#L57-L67)) |
| `desktop` + `desktop-file-ids` | **Да** | — | Атрибут не `$MISSING` → `allow-installation` не выполняется → `(NEEDS REVIEW)` ([`desktop.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/desktop.go#L57-L67), [desktop interface](https://snapcraft.io/docs/reference/interfaces/desktop-interface)) |
| `autostart:` | **Нет** | — | В review-tools нет ни одной проверки autostart; ключ только валидируется схемой ([`app.json`](https://git.launchpad.net/review-tools/tree/reviewtools/schemas/app.json?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca)) |
| `home` (обычный) | **Нет** | да на обычных дистрибутивах | `home` auto-connect: yes на традиционных дистрибутивах; на Ubuntu Core — нет ([home interface](https://snapcraft.io/docs/reference/interfaces/home-interface), [`home.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/home.go#L32-L47)) |
| `home` + `read: all` | **Да** | нет | `deny-connection` по `plug-attributes: read: all` → ревью ([`home.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/home.go#L32-L47)) |
| `personal-files` | **Да (до snap declaration)** | нет | `allow-installation: false` для plug → первый upload с этим plug требует snap declaration ([`personal_files.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/personal_files.go#L34-L38), [personal-files interface](https://snapcraft.io/docs/reference/interfaces/personal-files-interface)) |
| `system-files` | **Да (до snap declaration)** | нет | То же: `allow-installation: false` ([`system_files.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/system_files.go#L29-L33)) |
| `dbus` slot с `name:` | **Да (до snap declaration)** | нет | `deny-connection` по `slot-attributes: name: .+`; docs прямо говорят: нужен snap declaration и manual review ([`dbus.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/dbus.go#L38-L48), [dbus interface](https://snapcraft.io/docs/reference/interfaces/dbus-interface)) |
| `classic` | **Да, всегда + vetting** | — | Store флагует classic, publisher ветируется, нужен snap declaration; установка только с `--classic` ([Reviewing classic confinement snaps](https://snapcraft.io/docs/reference/administration/reviewing-classic-confinement-snaps/)) |

### 3.3 Главный скрытый триггер: `Gtk.Application` и D-Bus

LurkNotes создаёт `Gtk.Application(application_id="dev.lurknotes.LurkNotes",
flags=HANDLES_COMMAND_LINE)` (`src/lurkn/app.py:79-95`). Single-instance и активация
второго запуска у GApplication идут через сессионную шину: приложение пытается
занять well-known name, совпадающий с application id.

Под strict confinement **`desktop` не даёт приложению права `dbus (bind)`**: в его
AppArmor политике для приложения есть только `dbus (send/receive)` к конкретным
сервисам; `bind` разрешён только gnome-shell/gnome-settings-daemon
([`desktop.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/desktop.go)).
Чтобы владеть именем, нужен слот `dbus` с `bus: session` и `name:
dev.lurknotes.LurkNotes`; такой слот **всегда** уходит на ручное ревью
([dbus interface](https://snapcraft.io/docs/reference/interfaces/dbus-interface)).

Это ещё не решённый вопрос (он в тикете 03), но планировать нужно один из вариантов:

1. **Оставить Gtk.Application single-instance** → добавить dbus-slot → заложить
   ручное ревью (и, возможно, несколько дней ожидания).
2. **Убрать зависимость от D-Bus** (например, файловая блокировка в
   `$SNAP_USER_DATA` для single-instance) → ревью не нужно, но это изменение
   поведения/кода, а не только упаковки.

Проверить фактическое поведение без слота нужно на собранном снапе: возможно,
GApplication не падает, а просто теряет single-instance/активацию. Это дешёвый тест
на этапе упаковки.

### 3.4 Второй скрытый триггер: `desktop-file-ids`

Атрибут `desktop-file-ids` (snapd 2.66+) позволяет установить `.desktop` без
префикса имени снапа, чтобы ID файла не манглировался (это помогает связать окно
с launcher'ом/иконкой) ([desktop interface](https://snapcraft.io/docs/reference/interfaces/desktop-interface)).
Но именно этот атрибут нарушает `allow-installation` и даёт ручное ревью.

Компромисс:

- без атрибута — без ревью, но файл установится как
  `lurknotes_dev.lurknotes.LurkNotes.desktop`; для association можно попробовать
  `StartupWMClass` в .desktop;
- с атрибутом — красивее интеграция, но ревью.

Для 0.1.0 разумно начать без атрибута и проверить, как выглядит иконка/док; если
плохо — добавить атрибут и пройти ревью один раз.

### 3.5 Миграция данных из deb/pipx = `personal-files`

Приложение хранит заметки в `$XDG_DATA_HOME/lurknotes/notes.json`
(`src/lurkn/store.py:80`). На deb/pipx это `~/.local/share/lurknotes/notes.json`,
на snap — `$SNAP_USER_DATA/.local/share/lurknotes/notes.json` (snapd по умолчанию
не задаёт `XDG_DATA_HOME`, а `HOME=$SNAP_USER_DATA` —
[`snapenv.go`](https://github.com/canonical/snapd/blob/2.77.1/snap/snapenv/snapenv.go#L239-L252)).

Чтобы snap читал старый `~/.local/share/lurknotes`, нужен `personal-files` с
`read: [$HOME/.local/share/lurknotes]` — это **всегда** ручное ревью и отдельный
snap declaration. `home` здесь не поможет: `.local` — скрытый каталог, а `home`
даёт только не-скрытые файлы. Альтернатива без ревью — экспорт/импорт через
файловый chooser (портал), но это UX-изменение. Решение — тикеты 03/10/12.

### 3.6 Classic — почему это плохой запасной путь

Classic требует ручного ревью, ветеринга издателя и `--classic` при установке.
В списке **неподдерживаемых** причин прямо перечислены «difficulty making strict
confinement work», доступ к произвольным файлам и «access to dot files in $HOME»
([Reviewing classic confinement snaps](https://snapcraft.io/docs/reference/administration/reviewing-classic-confinement-snaps/)).
То есть «strict не воспроизводит поведение края» — не основание для classic.
Если strict+X11 не подойдёт, скорее надо менять механизм окна, а не просить classic.

### 3.7 Прочие флаги, которые стоит знать

- `type: base/kernel/gadget/snapd` — red flag, ревью ([`sr_lint.py`](https://git.launchpad.net/review-tools/tree/reviewtools/reviews/sr_lint.py?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca)).
- `grade: stable` при нестабильной base — ревью.
- Устаревший/неизвестный интерфейс — ревью.
- `daemon` + `browser-support` — предупреждение с `manual_review=True`.
- `system-usernames` вне allowlist — ошибка.
- Malware/security-скан Store может отправить снап в `ManualReviewPending` даже без
  интерфейсных флагов; в форуме есть случай, когда strict-снап (автор предполагал
  `network-bind`) пометили «potentially malicious» и сделали приватным без деталей
  ([Elmerfem thread](https://forum.snapcraft.io/t/elmerfem-snap-uploads-blocked-with-manualreviewpending-for-a-month/49144)).
  Для LurkNotes нет сетевых интерфейсов, риск ниже, но гарантий нет.

### 3.8 Сколько ждать и что делать

- Публичного SLA для общего ручного ревью найти не удалось. Для регистрации имени
  заявлен ориентир 2 рабочих дня; для ревью загрузки — только «очередь».
- Запросы на classic, privileged interfaces (включая `personal-files`,
  `system-files`, именованный `dbus`) и алиасы идут через форумный раздел
  `store-requests` с шаблоном подкатегории
  ([Process for aliases, auto-connections and tracks](https://snapcraft.io/docs/reference/administration/process-for-aliases-auto-connections-and-tracks)).
- Для `dbus` docs говорят просто «upload the snap and request a manual review»;
  для `personal-files` — «approved snap declaration» ([dbus](https://snapcraft.io/docs/reference/interfaces/dbus-interface),
  [personal-files](https://snapcraft.io/docs/reference/interfaces/personal-files-interface)).
- Пока ревью идёт, ревизия уже создана при upload (номер выдан), но в канале её
  нет; проверять `snapcraft revisions` и статус ревью в Store.

---

## 4. Сборка: snapcraft + LXD/Multipass/destructive/remote

### 4.1 Что нужно

- snapd ≥ 2.44.3, systemd, 2 ГБ RAM, 10 ГБ диска, сеть
  ([System requirements](https://documentation.ubuntu.com/snapcraft/stable/reference/system-requirements/)).
  На машине snapd 2.77.1 — подходит.
- Сам `snapcraft` ставится как classic-снап:
  `sudo snap install snapcraft --classic`
  ([Set up Snapcraft](https://documentation.ubuntu.com/snapcraft/stable/how-to/set-up-snapcraft/)).
- Build provider: для core22+ на Linux по умолчанию LXD; Multipass — на macOS/Windows
  и для core20 ([Select a build provider](https://documentation.ubuntu.com/snapcraft/stable/how-to/select-a-build-provider/)).

### 4.2 LXD (рекомендуемый путь для core24)

```bash
sudo snap install lxd
sudo usermod -a -G lxd "$USER"
# выйти и войти в сессию (или newgrp lxd)
groups "$USER"          # должен быть lxd
sudo lxd init --auto
```

Это ровно шаги из [Set up Snapcraft](https://documentation.ubuntu.com/snapcraft/stable/how-to/set-up-snapcraft/).
Важно: доступ к сокету LXD **эквивалентен root** — LXD прямо предупреждает давать
его только тем, кому вы доверили бы root
([LXD security](https://canonical.com/lxd/docs/latest/explanation/security/)).
То есть «сборка без sudo» достижима, но группа `lxd` — не песочница.

### 4.3 Multipass (альтернатива)

```bash
sudo snap install multipass
SNAPCRAFT_BUILD_ENVIRONMENT=multipass snapcraft
```

Для core22+ провайдер переопределяется переменной
`SNAPCRAFT_BUILD_ENVIRONMENT=multipass` или `snap set snapcraft provider=multipass`
([Select a build provider](https://documentation.ubuntu.com/snapcraft/stable/how-to/select-a-build-provider/)).
Multipass — VM; на вложенной виртуализации может не работать.

### 4.4 Destructive mode

```bash
sudo snapcraft --destructive-mode
```

Собирает прямо на хосте, без контейнера. Для core22+ **требует root**; не
рекомендуется на личной машине, потому что сборка может менять host (apt,
репозитории) ([Build environment options](https://documentation.ubuntu.com/snapcraft/stable/reference/build-environment-options/)).
Для core24 это не «сборка без root».

### 4.5 Remote build (без локальной VM/root)

```bash
snapcraft remote-build --launchpad-accept-public-upload
```

Сборка на Launchpad. Исходники по умолчанию **публично** загружаются на Launchpad;
нужен git-репозиторий в корне проекта, shallow clone не поддерживается; можно
указать приватный проект через `--project`
([Remote build](https://documentation.ubuntu.com/snapcraft/stable/explanation/remote-build/)).
Это хороший fallback, если LXD/Multipass недоступны, но не «приватная» сборка по
умолчанию.

### 4.6 core24 и архитектура

Для core24 используется `platforms`, а не `architectures`:

```yaml
base: core24
platforms:
  amd64:
    build-on: [amd64]
    build-for: [amd64]
```

Если имя платформы совпадает с архитектурой, достаточно `amd64:`
([Select platforms](https://documentation.ubuntu.com/snapcraft/stable/how-to/crafting/select-platforms/)).
`snapcraft init` в 9.2 подставляет `base: core26`, поэтому `base: core24` надо
выставить явно ([Configure package information](https://documentation.ubuntu.com/snapcraft/stable/how-to/crafting/configure-package-information/)).

### 4.7 Проверка до загрузки

```bash
snapcraft lint lurknotes_0.1.0_amd64.snap
sudo snap install --dangerous ./lurknotes_0.1.0_amd64.snap
snap run lurknotes
snap connections lurknotes
sudo snap remove lurknotes
```

`snapcraft lint` ставит снап в build environment и прогоняет линтеры
([lint](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/lint/)).
`--dangerous` — потому что локальный файл не подписан Store; это только для теста.

Дополнительно можно прогнать store-инструмент:

```bash
sudo snap install review-tools
snap-review ./lurknotes_0.1.0_amd64.snap
```

`snap-review` — тот же review-tools, что использует Store; exit 2 = errors,
1 = warnings, 0 = чисто ([review-tools README](https://git.launchpad.net/review-tools/tree/README)).
Он не заменяет человеческое ревью, но ловит механические ошибки до загрузки.

---

## 5. Каналы, ревизии, upload/release/rollback

### 5.1 Модель

Канал = `<track>/<risk>/<branch>`, по умолчанию track `latest`
([Channels](https://documentation.ubuntu.com/snapcraft/stable/reference/channels/)):

- track: `latest` для 0.1.0; свои track'и требуют одобрения Store.
- risk: `stable`, `candidate`, `beta`, `edge`. Пользователь по умолчанию ставит
  `stable`.
- branch: необязательная короткоживущая ветка; закрывается через 30 дней без
  новых ревизий.
- `grade: devel` нельзя публиковать в `stable`/`candidate`; для 0.1.0 нужен
  `grade: stable`.

Ревизия — автоматический номер при каждой загрузке; она неизменяема, номер не
означает порядок релиза ([Revisions](https://snapcraft.io/docs/explanation/how-snaps-work/revisions)).

### 5.2 Загрузка и публикация

```bash
# загрузить и сразу выпустить в edge
snapcraft upload --release=edge lurknotes_0.1.0_amd64.snap

# или сначала загрузить, потом выпустить
snapcraft upload lurknotes_0.1.0_amd64.snap
snapcraft release lurknotes <revision> edge

# несколько каналов сразу
snapcraft upload --release=edge,beta lurknotes_0.1.0_amd64.snap
```

`snapcraft upload --release` блокируется, пока Store не закончит обработку файла;
выводит channel map ([upload](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/upload/)).
Если автоматическая проверка нашла ошибки — команда даёт summary, нужно исправить
и загрузить новую ревизию; загрузка не «перезаписывает» старую
([Publish a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/publish-a-snap/)).

### 5.3 Продвижение в stable

```bash
snapcraft status lurknotes
snapcraft revisions lurknotes

snapcraft release lurknotes <revision> stable
# или интерактивно:
snapcraft promote lurknotes --from-channel=edge --to-channel=stable --yes
```

`promote` требует визуального подтверждения без `--yes`; `release` — прямая
команда ([promote](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/promote/),
[release](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/release/)).
Продвижение edge→stable — рекомендованный жизненный цикл
([Manage revisions and releases](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/manage-revisions-and-releases/)).

### 5.4 Откат

В Store **нет команды `rollback`**. Откат — это публикация старой ревизии в канал:

```bash
snapcraft revisions lurknotes          # найти предыдущую ревизию
snapcraft release lurknotes <old-rev> stable
```

Это demote текущей и promote старой; так же лечат «сломанный» релиз
([Manage revisions and releases](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/manage-revisions-and-releases/)).

На клиенте:

```bash
sudo snap revert lurknotes                 # вернуться на предыдущую ревизию
sudo snap refresh lurknotes --revision <rev>
```

`snap revert` откатывает к состоянию до последнего обновления и использует данные
предыдущей ревизии; изменения данных последней ревизии отменяются (локальная
проверка `snap revert --help`, snapd 2.77.1). `snap refresh --revision` ставит
конкретную ревизию ([Revisions](https://snapcraft.io/docs/explanation/how-snaps-work/revisions)).

### 5.5 Прочее

- Progressive release: `snapcraft release lurknotes <rev> stable --progressive 10`;
  после 100% всё равно нужен обычный релиз, потому что часть устройств игнорирует
  progressive ([Manage revisions and releases](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/manage-revisions-and-releases/)).
- Закрыть канал: `snapcraft close lurknotes edge` — канал начинает следовать
  следующему в цепочке ([close](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/close/)).
- `snapcraft status` показывает каналы и progressive-проценты; `snapcraft revisions`
  — все ревизии, а в колонке Channels видно, куда они выпущены
  ([Check a snap's status](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/check-a-snaps-status/)).

---

## 6. Что видит пользователь при `snap install`

### 6.1 Установка

```bash
sudo snap install lurknotes
# lurknotes 0.1.0 from <publisher> installed
```

Для strict-снапа **нет запроса разрешений**: `snap install` ставит его в strict
confinement, авто-подключает разрешённые интерфейсы и печатает одну строку
([Install modes](https://snapcraft.io/docs/explanation/snap-development/install-modes),
[Snap confinement](https://snapcraft.io/docs/explanation/security/snap-confinement)).
Единственное исключение — classic: установка требует явного `--classic`
([Install modes](https://snapcraft.io/docs/explanation/snap-development/install-modes)).

Проверить, что подключилось:

```bash
snap connections lurknotes
snap info lurknotes
```

`snap connections` покажет интерфейсы: `x11`, `desktop`, `desktop-legacy`,
`gsettings`, `opengl`, `wayland` (если используется GNOME extension) и `dbus`, если
он есть. Системные слоты отображаются как `:desktop`, `:home` и т.п. (локальная
проверка на `firmware-updater` показывает `:desktop`; пример для `home` — в
[home interface](https://snapcraft.io/docs/reference/interfaces/home-interface)).
`snap info` покажет summary, license, contact, description и каналы (локальная
проверка на `ktorrent`/`firefox`).

### 6.2 Иконка и меню

Если в `apps.<app>` задан `desktop:`, snapd при установке экспортирует `.desktop`
в системный каталог `/var/lib/snapd/desktop/applications/`, и приложение появляется
в меню/App Grid с иконкой
([Configure package information](https://documentation.ubuntu.com/snapcraft/stable/how-to/crafting/configure-package-information/);
локально: `/var/lib/snapd/desktop/applications/ktorrent_ktorrent.desktop`).
Иконка в меню — из `.desktop` (`Icon=`), а не из `icon:` в snapcraft.yaml; `icon:`
нужен для Store и графических фронтов.

### 6.3 Автозапуск

`autostart:` в `apps.<app>` — это **имя** desktop-файла, который приложение кладёт
в `$SNAP_USER_DATA/.config/autostart/`; snapd userd при старте сессии находит файлы
по этому пути и запускает приложение через wrapper, подставляя аргументы из `Exec=`
([snap format](https://snapcraft.io/docs/reference/development/yaml-schemas/the-snap-format),
[`autostart.go`](https://github.com/canonical/snapd/blob/2.77.1/usersession/autostart/autostart.go#L136-L186)).

Практические следствия:

- **Файл должен создать сам снап.** В тесте snapd приложение само пишет
  `$SNAP_USER_DATA/.config/autostart/foo.desktop`, и только потом `snap userd
  --autostart` его запускает
  ([test](https://github.com/canonical/snapd/blob/2.77.1/tests/main/snap-userd-desktop-app-autostart/task.yaml)).
  Объявить `autostart:` в snapcraft.yaml недостаточно.
- LurkNotes сейчас пишет файл только по `--install-autostart`
  (`src/lurkn/app.py:214-225`, `src/lurkn/autostart.py:76-108`). Если для snap
  убрать этот флаг (как решено в карте), автозапуск не появится, пока приложение
  не начнёт писать файл при первом обычном запуске (или пока это не сделает
  wrapper/hook). Это нужно учесть в тикете 08/09.
- Имя файла — `dev.lurknotes.LurkNotes.desktop` (`src/lurkn/autostart.py:16`), значит
  в snapcraft.yaml должно быть `autostart: dev.lurknotes.LurkNotes.desktop`.
- `OnlyShowIn=GNOME;` и `X-GNOME-Autostart-enabled=true` уже стоят в файле
  (`src/lurkn/autostart.py:60-71`); snapd учитывает `Hidden`,
  `X-GNOME-Autostart-enabled`, `OnlyShowIn`/`NotShowIn`
  ([`desktopentry.go`](https://github.com/canonical/snapd/blob/2.77.1/desktop/desktopentry/desktopentry.go#L200-L220)).
- Пользователь **не видит запроса** про автозапуск. Файл лежит в
  `~/snap/lurknotes/current/.config/autostart/`, а не в `~/.config/autostart/`,
  поэтому GNOME «Startup Applications» может его не показать. Отдельной команды
  `snap` для выключения autostart нет; пользователь может отредактировать
  `Hidden=true`/`X-GNOME-Autostart-enabled=false`, но приложение может перезаписать
  файл. Это UX-риск, который стоит закрыть собственным тумблером в приложении.

### 6.4 Обновления

Snap обновляется автоматически, по умолчанию 4 раза в день; пользователь может
`snap refresh --hold` или настроить `refresh.timer`
([Manage updates](https://snapcraft.io/docs/how-to-guides/manage-snaps/manage-updates)).
Это часть ожиданий: заметки не должны ломаться при смене ревизии, а данные лежат
в `$SNAP_USER_DATA`, который копируется между ревизиями
([Revisions](https://snapcraft.io/docs/explanation/how-snaps-work/revisions)).

### 6.5 Если понадобится `personal-files`

Тогда пользователь увидит интерфейс в `snap connections` **неподключённым**:
`personal-files` не авто-подключается, нужно `snap connect lurknotes:<plug>`.
Даже после одобрения snap declaration это разрешение, а не автоматика
([personal-files interface](https://snapcraft.io/docs/reference/interfaces/personal-files-interface)).
Это ещё один аргумент не тащить миграцию через personal-files без нужды.

---

## 7. Пошаговый чек-лист публикации

### Фаза 0 — аккаунт и имя (human-only)

1. Создать/войти в Ubuntu One через `https://snapcraft.io`.
2. Принять **Developer Programme Agreement** (Snap Store Terms + Privacy Notice)
   на `https://snapcraft.io/account/agreement`.
3. Включить 2FA в Ubuntu One (рекомендуется).
4. Поставить snapcraft:
   ```bash
   sudo snap install snapcraft --classic
   snapcraft --version
   ```
5. Войти:
   ```bash
   snapcraft login
   snapcraft whoami
   ```
6. Зарегистрировать имя. Лучше через `https://dashboard.snapcraft.io/register-snap/`,
   с комментарием «LurkNotes — заметки-колода у края экрана для GNOME; strict;
   x11; MIT». Если через CLI:
   ```bash
   snapcraft register lurknotes
   ```
   Затем проверить:
   ```bash
   snapcraft names
   ```
7. Дождаться одобрения имени (ориентир 2 рабочих дня). Не начинать загрузку, пока
   имя не выдано.

### Фаза 1 — сборка

8. Поставить LXD:
   ```bash
   sudo snap install lxd
   sudo usermod -a -G lxd "$USER"
   # перелогиниться
   groups "$USER"
   sudo lxd init --auto
   ```
9. В `snapcraft.yaml` выставить `base: core24`, `grade: stable`,
   `confinement: strict`, `platforms: amd64:`, `license: MIT`, `contact`,
   `website`, `icon`, `title`, `summary`, `description`.
10. Собрать:
    ```bash
    snapcraft
    ls -l lurknotes_0.1.0_amd64.snap
    ```
    (если LXD недоступен: `SNAPCRAFT_BUILD_ENVIRONMENT=multipass snapcraft` или
    `snapcraft remote-build --launchpad-accept-public-upload`).
11. Прогнать линтеры и локальную установку:
    ```bash
    snapcraft lint lurknotes_0.1.0_amd64.snap
    sudo snap install --dangerous ./lurknotes_0.1.0_amd64.snap
    snap run lurknotes
    snap connections lurknotes
    sudo snap remove lurknotes
    ```
12. По желанию — store-инструмент:
    ```bash
    sudo snap install review-tools
    snap-review ./lurknotes_0.1.0_amd64.snap
    ```
13. Проверить на чистой Ubuntu 24.04 (VM/LXD) установку, запуск, край, заметки,
    autostart после первого запуска и перезагрузки.

### Фаза 2 — первый релиз в edge

14. Загрузить:
    ```bash
    snapcraft upload --release=edge lurknotes_0.1.0_amd64.snap
    ```
15. Посмотреть ревизию и статус:
    ```bash
    snapcraft revisions lurknotes
    snapcraft status lurknotes
    ```
16. Если ревизия не появилась в канале — проверить статус ревью в Store (например,
    `ManualReviewPending`). Для `dbus`/`personal-files`/`classic` — запросить ревью в
    форумном `store-requests` по шаблону; для обычного сбоя авто-ревью — исправить и
    загрузить новую ревизию.
17. Установить из Store на чистой машине:
    ```bash
    sudo snap install lurknotes --channel=edge
    snap run lurknotes
    ```

### Фаза 3 — листинг

18. Открыть `https://snapcraft.io/lurknotes/listing`.
19. Заполнить: Title `LurkNotes`; Summary ≤ 78; Description (Markdown); Category
    `utilities`; Developer website — GitHub; Contact — `aytpaev@gmail.com`;
    License `MIT`; Icon 256×256 PNG; 3–5 скриншотов; при желании баннер/видео.
20. Сохранить. Проверить `https://snapcraft.io/lurknotes` и
    `snap info lurknotes`.
21. Не запускать `snapcraft upload-metadata --force` после ручных правок, если не
    хотите перетереть листинг.

### Фаза 4 — stable

22. Ещё раз проверить edge на чистой машине.
23. Выпустить в stable:
    ```bash
    snapcraft release lurknotes <revision> stable
    # или
    snapcraft promote lurknotes --from-channel=edge --to-channel=stable --yes
    ```
24. Проверить:
    ```bash
    snapcraft status lurknotes
    snap info lurknotes
    sudo snap install lurknotes        # на чистой машине
    ```
25. Записать ревизию, дату, ссылку на листинг в тикет 06/11.

### Фаза 5 — откат/инцидент

26. Store-side откат:
    ```bash
    snapcraft revisions lurknotes
    snapcraft release lurknotes <previous-rev> stable
    ```
27. Client-side:
    ```bash
    sudo snap revert lurknotes
    sudo snap refresh lurknotes --revision <previous-rev>
    ```
28. При необходимости закрыть канал:
    ```bash
    snapcraft close lurknotes edge
    ```

---

## 8. Неопределённости и риски

1. **Регистрация имени не мгновенная.** Политика 2024 года требует ручной проверки;
   целевой срок 2 рабочих дня, но фактический может быть больше. В CLI
   `snapcraft register` комментарий не спрашивает — неясно, попадёт ли контекст в
   заявку; веб-форма надёжнее. (Проверено по коду snapcraft и policy post, не по
   живому аккаунту.)
2. **Нет публичного SLA для ревью загрузки.** Для name registration ориентир есть,
   для interface/manual review — нет. В форуме есть случаи ожидания месяц и
   пометки «potentially malicious» без деталей. Планировать буфер.
3. **`dbus`-слот и Gtk.Application.** Не проверено на собранном снапе, падает ли
   приложение без права занять `dev.lurknotes.LurkNotes`, или просто теряет
   single-instance. Если нужен слот — это гарантированное ручное ревью; если можно
   обойтись файловой блокировкой — лучше обойтись. Решение — тикет 03.
4. **`desktop-file-ids`.** Красивая интеграция с GNOME требует атрибута, который
   триггерит ревью. Нужно проверить внешний вид без атрибута (иконка в доке,
   Alt+Tab, association) до того, как соглашаться на ревью.
5. **`autostart` без файла.** Главный риск упаковки: `autostart:` не создаёт файл.
   Нужно изменение кода/обёртки, иначе автозапуск в snap не работает. Это не
   проверено на снапе, но следует из кода snapd и текущего кода LurkNotes.
6. **Автозапуск и UX.** Пользователь не даёт согласия на автозапуск; отдельного
   тумблера в snap нет; файл в `~/snap/.../.config/autostart` может быть не виден
   GNOME «Startup Applications». Нужен собственный тумблер или явное объяснение в
   онбординге.
7. **Лимиты листинга.** Иконка/скриншоты/баннер проверены по JS snapcraft.io master;
   Store может менять лимиты без обновления docs. Форма — источник истины.
8. **Keywords.** Поля нет; если keywords уже согласованы в тикете 07, это ошибка —
   убрать.
9. **Metadata sync.** Поведение Store при загрузке новой ревизии (перетирает ли
   ручной листинг) не проверено на живом аккаунте; флаг
   `update_metadata_on_release` в контексте формы есть, но в шаблоне не отрендерен.
   После первого релиза проверить, не слетели ли тексты.
10. **`snap-review` vs Store.** Локальный review-tools может быть старше/новее
    серверного; зелёный `snap-review` не гарантирует отсутствие ручного флага
    (malware scan, policy).
11. **`home`/`personal-files` для миграции.** Если понадобится читать
    `~/.local/share/lurknotes`, это `personal-files` → ревью + ручное подключение.
    Альтернатива — экспорт/импорт, но это UX-изменение. Решение — тикеты 10/12.
12. **Classic.** Не запасной путь: «strict не работает» — неподдерживаемая причина;
    classic требует vetting и `--classic` у пользователя.

---

## 9. Источники

### Первичные: Snapcraft / Snap docs

- [Register a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/register-a-snap/) — аккаунт, `snapcraft login`, 2FA, правила имени, `snapcraft register`.
- [Publish a snap](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/publish-a-snap/) — первый upload, авто-ревью, `--release`.
- [Manage revisions and releases](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/manage-revisions-and-releases/) — upload/release/promote/progressive/demote.
- [Channels](https://documentation.ubuntu.com/snapcraft/stable/reference/channels/) — track/risk/branch, grade, 30 дней.
- [Revisions](https://snapcraft.io/docs/explanation/how-snaps-work/revisions) — номера, хранение, `--revision`.
- [Check a snap's status](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/check-a-snaps-status/) — `status`, `revisions`, `names`.
- [upload](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/upload/), [release](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/release/), [promote](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/promote/), [close](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/close/), [upload-metadata](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/upload-metadata/), [lint](https://documentation.ubuntu.com/snapcraft/stable/reference/commands/lint/).
- [snapcraft.yaml reference](https://documentation.ubuntu.com/snapcraft/stable/reference/snapcraft-yaml/) — `title`, `summary`, `description`, `license`, `contact`, `website`, `icon`, `autostart`, `grade`, `platforms`.
- [Configure package information](https://documentation.ubuntu.com/snapcraft/stable/how-to/crafting/configure-package-information/) — desktop entry, icon vs desktop icon, core26 default.
- [Select platforms](https://documentation.ubuntu.com/snapcraft/stable/how-to/crafting/select-platforms/) — `platforms` для core24+.
- [Set up Snapcraft](https://documentation.ubuntu.com/snapcraft/stable/how-to/set-up-snapcraft/) — snapcraft + LXD/Multipass, группа `lxd`.
- [Select a build provider](https://documentation.ubuntu.com/snapcraft/stable/how-to/select-a-build-provider/) — LXD по умолчанию на Linux, Multipass, override.
- [Build environment options](https://documentation.ubuntu.com/snapcraft/stable/reference/build-environment-options/) — destructive mode, root для core22+.
- [Remote build](https://documentation.ubuntu.com/snapcraft/stable/explanation/remote-build/) — Launchpad, публичная загрузка, git, no shallow.
- [System requirements](https://documentation.ubuntu.com/snapcraft/stable/reference/system-requirements/) — 2 ГБ RAM, 10 ГБ, snapd 2.44.3+.
- [Install modes](https://snapcraft.io/docs/explanation/snap-development/install-modes) — strict без prompt, classic с `--classic`, `--dangerous`.
- [Snap confinement](https://snapcraft.io/docs/explanation/security/snap-confinement) — strict/classic/devmode.
- [Interface auto-connection](https://snapcraft.io/docs/explanation/interfaces/interface-auto-connection) — как snapd авто-подключает.
- [Snap format](https://snapcraft.io/docs/reference/development/yaml-schemas/the-snap-format) — `autostart`, desktop files, `$SNAP_USER_DATA/.config/autostart`.
- [Manage updates](https://snapcraft.io/docs/how-to-guides/manage-snaps/manage-updates) — 4 refresh/day, `snap refresh --hold`.
- [Reviewing classic confinement snaps](https://snapcraft.io/docs/reference/administration/reviewing-classic-confinement-snaps/) — флаг classic, vetting, supported/unsupported.
- [Process for aliases, auto-connections and tracks](https://snapcraft.io/docs/reference/administration/process-for-aliases-auto-connections-and-tracks) — форумный процесс.
- [x11 interface](https://snapcraft.io/docs/reference/interfaces/x11-interface), [desktop interface](https://snapcraft.io/docs/reference/interfaces/desktop-interface), [home interface](https://snapcraft.io/docs/reference/interfaces/home-interface), [personal-files interface](https://snapcraft.io/docs/reference/interfaces/personal-files-interface), [dbus interface](https://snapcraft.io/docs/reference/interfaces/dbus-interface).

### Первичные: snapd 2.77.1 (source)

- [`interfaces/builtin/x11.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/x11.go#L37-L48) — base declaration x11.
- [`interfaces/builtin/desktop.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/desktop.go#L57-L67) — `desktop-file-ids` / `$MISSING`.
- [`interfaces/builtin/home.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/home.go#L32-L47) — `read: all`, auto-connect.
- [`interfaces/builtin/personal_files.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/personal_files.go#L34-L38), [`system_files.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/system_files.go#L29-L33) — `allow-installation: false`.
- [`interfaces/builtin/dbus.go`](https://github.com/canonical/snapd/blob/2.77.1/interfaces/builtin/dbus.go#L38-L48) — `deny-connection` для именованного slot.
- [`usersession/autostart/autostart.go`](https://github.com/canonical/snapd/blob/2.77.1/usersession/autostart/autostart.go#L136-L186) — `snap userd --autostart`.
- [`desktop/desktopentry/desktopentry.go`](https://github.com/canonical/snapd/blob/2.77.1/desktop/desktopentry/desktopentry.go#L200-L220) — Hidden/X-GNOME-Autostart-enabled/OnlyShowIn.
- [`snap/snapenv/snapenv.go`](https://github.com/canonical/snapd/blob/2.77.1/snap/snapenv/snapenv.go#L239-L252) — HOME/XDG_DATA_HOME/XDG_CONFIG_HOME под strict.
- [`tests/main/snap-userd-desktop-app-autostart/task.yaml`](https://github.com/canonical/snapd/blob/2.77.1/tests/main/snap-userd-desktop-app-autostart/task.yaml) — приложение само пишет autostart-файл.

### Первичные: review-tools (Store review)

- [review-tools repo](https://git.launchpad.net/review-tools/) — commit `8368bbd5a4e44041429561a3ef20c69e4abe48ca` (2026-10-26).
- [`reviewtools/reviews/sr_lint.py`](https://git.launchpad.net/review-tools/tree/reviewtools/reviews/sr_lint.py?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca) — classic, base stable, personal/system files path checks; desktop file info.
- [`reviewtools/reviews/sr_declaration.py`](https://git.launchpad.net/review-tools/tree/reviewtools/reviews/sr_declaration.py?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca) — installation/connection constraints → `manual_review=True`.
- [`reviewtools/schemas/app.json`](https://git.launchpad.net/review-tools/tree/reviewtools/schemas/app.json?h=8368bbd5a4e44041429561a3ef20c69e4abe48ca) — `autostart` только схема.
- [`README`](https://git.launchpad.net/review-tools/tree/README) — `snap-review`, exit codes.
- `snap info review-tools` — snap 0.48+20260921, издатель Canonical, «used by the Ubuntu store».

### Первичные: snapcraft.io (листинг)

- [`templates/publisher/listing.html`](https://github.com/canonical/snapcraft.io/blob/master/templates/publisher/listing.html) — поля формы, `required`, maxlength, «updates appear immediately», Markdown.
- [`webapp/publisher/snaps/listing_views.py`](https://github.com/canonical/snapcraft.io/blob/master/webapp/publisher/snaps/listing_views.py) — какие поля принимает backend (keywords отсутствует).
- [`static/js/publisher/form/icon.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/icon.js) — 40–512, 1:1, 256 KB, PNG/JPEG/SVG.
- [`static/js/publisher/form/media.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/media.js) — 5 изображений, 480×480–3840×2160, 1:2–2:1, 2 MB, GIF/JPEG/PNG.
- [`static/js/publisher/form/banner.js`](https://github.com/canonical/snapcraft.io/blob/master/static/js/publisher/form/banner.js) — 720×240–4320×1440, 3:1, 2 MB.
- [Store API categories](https://api.snapcraft.io/v2/snaps/categories) — 20 слагов, включая `utilities`.
- [Store API info lurknotes](https://api.snapcraft.io/v2/snaps/info/lurknotes) — 404 на 2026-10-28.

### Первичные: юридические / политика

- [Snap Store Terms of Service](https://canonical.com/legal/terms-and-policies/snap-store-terms) — §3 аккаунт, §4.1/4.3 публикация/удаление, §5 запрещённый контент, §6.2 лицензия.
- [Developer Programme Agreement](https://snapcraft.io/account/agreement) — текущая страница принятия Terms + Privacy Notice.
- [Manual review of all new snap name registrations](https://forum.snapcraft.io/t/manual-review-of-all-new-snap-name-registrations/39440) — политика ручной проверки имён, 2 рабочих дня.
- [Store listing and branding](https://forum.snapcraft.io/t/store-listing-and-branding/16397) — архивная doc-страница с требованиями к медиа (совпадает с текущим JS).

### Локальные проверки (воспроизводимо)

- `snap --version` → `snap 2.77.1+ubuntu24.04`, snapd 2.77.1.
- `snap info review-tools` → 0.48+20260921, Canonical, описание про `snap-review`.
- `snap revert --help` → откат к предыдущей ревизии и данным.
- `snap info ktorrent` / `snap info firefox` → `snap info` показывает license/contact/summary/description/channels.
- `snap connections firmware-updater` → интерфейсы и слоты видны пользователю.
- `ls /var/lib/snapd/desktop/applications/` → экспортированные `.desktop` снапов.
- `GET https://api.snapcraft.io/v2/snaps/info/lurknotes` → 404 (имя не занято опубликованным снапом).
- `GET https://api.snapcraft.io/v2/snaps/categories` → список слагов.
- Клон `review-tools` (Launchpad) и `snapd` 2.77.1 для проверки кода; `snapcraft`/`snapcraft.io` — по исходникам на GitHub.
