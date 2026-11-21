# Схема хранения и синхронизации в Laravel 13: результаты исследования

Дата проверки: 2026-11-21.
Основание: `web/` — свежий скелет Laravel 13 (`laravel/framework` v13.43.0 в
`composer.lock`, `php ^8.3`, PHP 8.4.1 в контейнере, SQLite 3.43.2 как БД по
умолчанию, `QUEUE_CONNECTION=database`, `SESSION_DRIVER=database`).
Метод: чтение `vendor/` (исходники фреймворка 13.43.0), документация Laravel
`13.x` (`laravel/docs`, ветка `13.x`), исходники Sanctum `4.x`, Fortify `1.x`,
Scramble `main` и метаданные Packagist. Composer и artisan не запускались,
ничего не устанавливалось.

---

## Краткий вывод

**Всё, что нужно для серверной части синхронизации, есть из коробки, кроме
двух пакетов: `laravel/sanctum` и `laravel/fortify`.** Схема
(`user_id` + клиентский UUID, `deleted_at`, интервальные запросы) выражается
штатным Schema Builder без сырого SQL; SQLite годится, но с двумя оговорками —
размер индекса и блокировки записи.

- **Схема.** `$table->unique(['user_id', 'client_id'])` — составной уникальный
  индекс; `$table->softDeletes()` — nullable `deleted_at`; интервал —
  `WHERE server_updated_at > ?` с индексом `(user_id, server_updated_at)`.
  На SQLite и MySQL это одно и то же API; Laravel сам подбирает грамматику.
- **Sanctum.** `$user->createToken($deviceName, ['sync'])` возвращает
  `NewAccessToken` с `plainTextToken` вида `{id}|{random}`; в
  `personal_access_tokens` хранится **SHA-256 хеш** токена, а не сам токен.
  Отзыв — `$request->user()->currentAccessToken()->delete()` или
  `$user->tokens()->where('id', $id)->delete()`.
- **Fortify vs Breeze.** В Laravel 13 официальных веб-стартер-китов без
  JS-фронтенда нет: все киты (React/Svelte/Vue/Livewire) используют Fortify и
  тянут Inertia/Vite. Breeze — «для Laravel 11.x и ранее», для 13 не
  поддерживается. Выбор — **Fortify** с собственными Blade-вьюхами; маршруты
  входа приходят из пакета, не пишутся руками.
- **OpenAPI.** **Scramble** генерирует OpenAPI 3.1.0 прямо из кода (роуты +
  валидация + типы ответов), из коробки отдаёт `/docs/api.json`, в CI —
  `php artisan scramble:export`. Laravel 13 он поддерживает
  (`illuminate/contracts ^10–^13`). Scribe тоже знает Laravel 13, но работает
  по-другому: строит вывод из документационных тегов, поэтому легко
  рассинхронизируется с кодом. **Рекомендация — Scramble.**
- **Ретенция надгробий.** Отдельный queue worker **не нужен**:
  `Schedule::command('notes:purge-tombstones')->daily()` в `routes/console.php`
  + одна cron-строка `schedule:run` на сервере. Очередь понадобится, только
  если чистка станет тяжёлой или её захочется дёргать из HTTP-запроса.
- **Валидация.** `uuid:4` проверяет конкретно UUID v4 (`Str::isUuid($v, 4)`).
  Гонки при позициях лечатся **одним правилом**: клиент не выводит порядок из
  чужих значений, а при перестановке отправляет явный список задетых заметок;
  сервер применяет его в одной транзакции с `SELECT ... FOR UPDATE` по
  `user_id`.

---

## Ответы

### 1. Схема БД в миграциях Laravel 13

#### 1.1 Составной уникальный индекс

`Blueprint::unique()` принимает массив колонок; имя индекса по умолчанию
`{table}_{col1}_{col2}_unique`
(`vendor/laravel/framework/src/Illuminate/Database/Schema/Blueprint.php:673`,
`indexCommand()` там же, строка 1783). Грамматики базы подставляют своё
написание `CREATE UNIQUE INDEX`, поэтому один и тот же `Blueprint` работает и
на SQLite, и на MySQL:

```php
Schema::create('notes', function (Blueprint $table) {
    $table->id();
    $table->foreignId('user_id')->constrained()->cascadeOnDelete();

    // ID заметки, который выдал клиент. UUID4 в канонической записи
    // (36 символов, нижний регистр) — но длина строки, а не CHAR(36):
    // это переносимо и между SQLite/MySQL, и между драйверами.
    $table->string('client_id', 36);

    $table->text('text')->default('');
    $table->double('position')->default(0);

    // «Последняя запись побеждает» по серверному времени.
    $table->timestamp('server_updated_at', precision: 6)->useCurrent();
    $table->softDeletesTz();          // deleted_at, nullable

    $table->timestamps();

    // Один и тот же UUID допустим у разных пользователей, но не дважды у одного.
    $table->unique(['user_id', 'client_id']);

    // Интервальный запрос pull: WHERE user_id = ? AND server_updated_at > ?
    $table->index(['user_id', 'server_updated_at']);
    // Порядок в списке на сайте.
    $table->index(['user_id', 'position']);
});
```

Документация: «Компаундные индексы можно создавать, передав массив колонок в
метод индекса» —
<https://github.com/laravel/docs/blob/13.x/migrations.md#creating-indexes>.

Три решения, которые спека должна зафиксировать явно:

1. **`string(36)`, не `uuid`/`char(36)`.** Тип `uuid` в Laravel — это
   псевдоним: на SQLite он станет `varchar` без изменений, на MySQL —
   `char(36)`; `string(36)` ведёт себя одинаково на обеих и не мешает позже
   сменить СУБД. Сравнение по строке чувствительно к регистру на MySQL по
   умолчанию (collation `utf8mb4_0900_ai_ci` **не** чувствителен к регистру),
   а SQLite `=` строки сравнивает побайтно. **Правило спеки:** клиент шлёт
   UUID в нижнем регистре, сервер валидирует `uuid:4` и дополнительно
   проверяет регуляркой `^[0-9a-f]{8}-…$` (см. §6.1), чтобы одна и та же
   заметка не создалась дважды на MySQL с разным регистром.
2. **`position` как `double`.** Решение 2.2 фиксирует «порядок — число на
   заметке», а не дробный индекс Линда. `double` на SQLite — `REAL`, на
   MySQL — `double`; сортировка по нему стабильна, но при равных значениях
   нужен вторичный ключ (см. §6.3).
3. **Составной уникальный индекс — это и есть защита от дублей при push.**
   Клиент может повторить отправку после таймаута; вставка второй строки с
   тем же `(user_id, client_id)` упадёт `UniqueConstraintViolationException`,
   и сервер сделает апдейт (см. §6.2) вместо создания клона.

#### 1.2 Soft deletes

`$table->softDeletes()` — это `timestamp('deleted_at')->nullable()`
(`Blueprint.php:1391`); есть варианты `softDeletesTz()` и
`softDeletesDatetime()`. На стороне модели — трейт `SoftDeletes`:
по умолчанию удалённые строки скрыты, `withTrashed()`/`onlyTrashed()` их
показывают, `restore()` и `forceDelete()` работают как ожидается
(<https://github.com/laravel/docs/blob/13.x/eloquent.md#soft-deleting>).

**Важно для протокола:** `SoftDeletes` — это **семантика Eloquent**, а не
столбец БД. Надгробие в синхронизации живёт 30 дней и **должно попадать в
pull-ответ**, иначе второе устройство никогда не узнает об удалении. Готовое
решение: добавлять надгробия в выборку явно —

```php
// pull: и живые, и надгробия, всё, что новее клиентской отметки
Note::withTrashed()
    ->where('user_id', $user->id)
    ->where('server_updated_at', '>', $since)
    ->orderBy('server_updated_at')
    ->orderBy('id')
    ->get();
```

`delete()` по модели проставит `deleted_at = now()`, но **не** обновит
`server_updated_at` — трейт `SoftDeletes` в 13.x самостоятельного
`addUpdatedAtColumn` не вызывает. В приложении это надо делать в одном месте
(сервис/модель), например:

```php
DB::transaction(function () use ($note) {
    $note->deleted_at = now();
    $note->server_updated_at = now();
    $note->save();
});
```

Эту деталь спека должна назвать, иначе удаление «утопленника» не доедет до
клиента при инкрементальном pull.

#### 1.3 Интервальные запросы

`where('server_updated_at', '>', $since)` — обычное условие Query Builder.
`>` (строго) важен: если клиент запомнил `server_timestamp` последней
пришедшей заметки, то `>` и фильтр `server_updated_at > $since`
дадут ровно новые записи. Опасность — **несколько записей с одинаковым
`server_updated_at`**: при точности 6 знаков после запятой они возможны, если
два устройства пушат одновременно. Отсюда `orderBy('server_updated_at')` +
`orderBy('id')` и правило протокола: клиент хранит `since` как значение
последнего *выданного* `server_updated_at`, а сервер, если строк с этим
значением может быть больше одной, отдаёт их все — простой `>` это
обеспечивает, потому что все они получат `>$since` при ровно том же
`since`.

**Особенности SQLite/MySQL:**

- *Точность:* `precision: 6` даёт `datetime(6)` на MySQL и TEXT с
  микросекундами на SQLite (SQLite хранит даты как TEXT). Если взять
  `precision: 0`, таймстемпы в пределах секунды сравняются, и «последняя
  запись побеждает» начнёт зависеть от порядка прихода. Для
  `server_updated_at` нужна точность 6.
- *Строковое сравнение дат:* на SQLite `server_updated_at > '2026-11-21 12:00:00.000000'`
  сравнивает TEXT лексикографически — работает, только пока все значения
  пишутся в одинаковом формате (`Y-m-d H:i:s.u`). Laravel подставляет дату
  через биндинг в формате соединения, поэтому формат одинаков, пока формат не
  меняют руками; **не** пишите в эту колонку строки из JS-клиента.
- *Часовой пояс:* Laravel по умолчанию `UTC`, MySQL TIMESTAMP конвертирует
  время в UTC сам, SQLite — как строку. Приложение должно держать
  `APP_TIMEZONE=UTC` (значение по умолчанию) и не хранить локальное время.
- *Блокировки:* на SQLite писатель один на базу. `UPDATE` берёт
  блокировку; при высоком параллелизме push'ей стоит включить WAL и
  `busy_timeout` (см. §6.2). На MySQL InnoDB свойство «одна строка — один
  писатель» уже гарантирует сам движок, но **MySQL не блокирует отсутствующие
  строки** (нет range-lock'а без serializable), поэтому «проверить, что нет
  — вставить» и рвётся; отсюда `firstOrCreate`/`createOrFirst` и
  `UniqueConstraintViolationException` (см. §6.2).

### 2. Sanctum: токен устройства, abilities, отзыв

#### 2.1 Что нужно установить

`laravel/sanctum` в `web/` **не установлен** (`vendor/laravel/` — только
`agent-detector`, `framework`, `pail`, `pao`, `pint`, `prompts`,
`serializable-closure`, `tinker`). Версия на Packagist — v4.5.0
(2026-11-11), требует `php ^8.2` и `illuminate/* ^12.0|^13.0`, то есть
Laravel 13 поддерживается. После установки — публикация миграции
`personal_access_tokens` и трейт `HasApiTokens` на `User`:

```php
use Laravel\Sanctum\HasApiTokens;

class User extends Authenticatable
{
    use HasApiTokens, HasFactory, Notifiable;
}
```

Официальная инструкция:
<https://github.com/laravel/docs/blob/13.x/sanctum.md#installation>.

#### 2.2 Выдача токена устройства

`HasApiTokens::createToken(string $name, array $abilities = ['*'], ?DateTimeInterface $expiresAt = null)`
(`vendor` тут нет, потому что пакет не установлен; исходник —
<https://github.com/laravel/sanctum/blob/4.x/src/HasApiTokens.php#L60>):

```php
// POST /api/sync/tokens  (auth:sanctum, session)
Route::post('/sync/tokens', function (Request $request) {
    $request->validate([
        'device_name' => ['required', 'string', 'max:100'],
    ]);

    $token = $request->user()->createToken(
        name: $request->device_name,
        abilities: ['sync'],
    );

    return ['token' => $token->plainTextToken]; // показывать один раз
});
```

`plainTextToken` в текущей версии — `$token->getKey().'|'.$random`, где
`$random` — 40 символов `Str::random` (плюс `config('sanctum.token_prefix')`,
если задан). Хранится в БД **`hash('sha256', $plainTextToken)`**, а не
открытый текст. Токен должен уйти клиенту ровно один раз: Sanctum
не умеет восстанавливать plaintext.

**Важно для протокола:** в `personal_access_tokens` нет поля
«устройство» кроме `name` и `abilities`. Уникальность токена на устройство
надо обеспечить приложением: при выдаче нового токена на то же
`device_name` удалять прежний (`$user->tokens()->where('name', $deviceName)->delete()`),
иначе у пользователя копятся «мёртвые» токены, которые никто не отзовёт.

#### 2.3 Что хранится в `personal_access_tokens`

Миграция пакета:

<https://github.com/laravel/sanctum/blob/4.x/database/migrations/2019_12_14_000001_create_personal_access_tokens_table.php>

| колонка | тип | замечание |
|---|---|---|
| `id` | bigint PK | |
| `tokenable_type`, `tokenable_id` | morph | `morphs('tokenable')` → `users` |
| `name` | text | имя устройства; в API показывать людям |
| `token` | `string(64)` unique | SHA-256 хеш, не токен |
| `abilities` | text nullable | JSON-массив строк; `*` — все |
| `last_used_at` | timestamp | обновляется при аутентификации |
| `expires_at` | timestamp nullable, index | `config('sanctum.expiration')` в минутах, если задан |
| `created_at`, `updated_at` | timestamps | |

#### 2.4 Отзыв

<https://github.com/laravel/docs/blob/13.x/sanctum.md#revoking-tokens>
— четыре готовых идиомы:

```php
$request->user()->currentAccessToken()->delete();            // logout устройства
$user->tokens()->where('id', $tokenId)->delete();            // отозвать конкретный
$user->tokens()->delete();                                   // «выйти везде»
$user->tokens()->where('name', $device)->delete();           // перед выдачей нового
```

При аутентификации сессией (cookie) `currentAccessToken()` возвращает
`TransientToken`, и `->delete()` у него — no-op; поэтому logout устройства
надо проверять: если `currentAccessToken() instanceof \Laravel\Sanctum\TransientToken`,
отзывать нечего (см. `Guard::__invoke`, который оборачивает сессионного
пользователя в `TransientToken`,
<https://github.com/laravel/sanctum/blob/4.x/src/Guard.php#L30>).

#### 2.5 Abilities

`$request->user()->tokenCan('sync')` (документация —
`sanctum.md#token-abilities`). Для LurkNotes достаточно **одной** способности
`sync`; дальше полагаться на `user_id` в каждом запросе, а не на broad
abilities. `abilities` — это JSON (`PersonalAccessToken::$casts['abilities'] = 'json'`),
так что значений с «<» и прочим экранированием не надо.

#### 2.6 Гвард и порядок проверки

`config/sanctum.php` по умолчанию: `'guard' => ['web']` — сначала
проверяется сессионная кука, затем bearer-токен
(<https://github.com/laravel/sanctum/blob/4.x/config/sanctum.php>). Это ровно
то, что нужно: на сайте `/notes` открывается по сессии, а десктоп ходит по
токену, и оба живут на `auth:sanctum`.

### 3. Fortify vs Breeze для email + пароль + веб-сессии

#### 3.1 Что есть в Laravel 13

Официальные стартер-киты 13.x — React, Svelte, Vue, Livewire; **все
используют Fortify** и ставят Inertia/Vite/Tailwind
(<https://github.com/laravel/docs/blob/13.x/starter-kits.md#authentication>).
Веб-кита «Blade без JS» в списке нет. Breeze в ветке `2.x` начинается
дословно с: «This starter kit is for Laravel 11.x and prior»
(<https://github.com/laravel/breeze/blob/2.x/README.md>); его
`composer.json` формально допускает `illuminate/support ^13.0`
(v2.4.2, 2026-05-14,
<https://repo.packagist.org/p2/laravel/breeze.json>), но апстрим объявил его
устаревшим. Ставить Breeze в Laravel 13 — идти против явного указания
апстрима.

#### 3.2 Что даёт Fortify

`laravel/fortify` v1.43.0 (2026-11-14) требует `illuminate/support ^12.0|^13.0`,
то есть Laravel 13 поддерживает. После `php artisan fortify:install`
публикуются: `app/Actions/Fortify/*` (CreateNewUser, UpdateUserPassword, …),
`config/fortify.php`, `FortifyServiceProvider` и **миграции**
(`password_reset_tokens` уже есть в скелете;
двухфакторная миграция — только если включены 2FA-фичи). `Features` по
умолчанию — регистрация, сброс пароля, верификация почты, профиль, пароль,
2FA, passkeys
(<https://github.com/laravel/fortify/blob/1.x/config/fortify.php>).
Fortify **не приносит вьюх**: «Since Fortify does not provide its own user
interface, it is meant to be paired with your own user interface»
(<https://github.com/laravel/docs/blob/13.x/fortify.md#what-is-fortify>).
Blade-шаблоны `login`, `register`, `forgot-password`, `reset-password`,
`verify-email` пишутся руками — их десяток небольших файлов.

#### 3.3 Где живут маршруты входа

Маршруты регистрирует сам пакет, в приложении их нет
(<https://github.com/laravel/fortify/blob/1.x/routes/routes.php>):

| метод | URI | имя | middleware |
|---|---|---|---|
| GET | `/login` | `login` | `guest` |
| POST | `/login` | `login.store` | `guest`, `throttle` (если `fortify.limiters.login`) |
| POST | `/logout` | `logout` | `auth` |
| GET/POST | `/register` | `register*` | `guest` |
| GET/POST | `/forgot-password`, `/reset-password/{token}` | `password.request`, `password.email`, `password.reset`, `password.update` | `guest` |

Префикс и пути меняются в `config/fortify.php` (`'prefix'`, `'domain'`,
`'paths'`). В `web/` нет `/login` — как только `laravel/framework` в
`bootstrap/app.php` не находит owned-роут на `login`, `auth`-middleware
редиректит на **имя** `login`, так что `Route::get('/notes')->middleware('auth')`
заработает без изменений в `web/routes`.

#### 3.4 Вердикт

**Fortify.** Breeze — устаревший; стартер-киты — тянут JS-стек, которого у
сайта нет (веб-UI — «список заметок и открытие одной», решение 4.3).
Fortify + свои Blade-вьюхи даёт веб-сессии (те же `sessions` таблицы
скелета), и рядом живёт Sanctum для токенов устройств. В `config/fortify.php`
для LurkNotes стоит выключить лишнее:

```php
'features' => [
    Features::registration(),
    Features::resetPasswords(),
    Features::emailVerification(),
    // Features::twoFactorAuthentication(), // Post-MVP
    // Features::passkeys(),                 // Post-MVP
],
```

Для регистрации по email+паролю хватит `CreateNewUser` и
`UpdateUserPassword`; `UpdateUserProfileInformation` — если на сайте будет
смена имени/почты.

### 4. OpenAPI: Scramble vs Scribe для Laravel 13

#### 4.1 Scramble — что генерирует

Scramble генерирует **OpenAPI 3.1.0** без PHPDoc-аннотаций: типы берутся из
валидации (`$request->validate()`, FormRequest), возвращаемых типов
контроллеров, Eloquent-моделей и JsonResource
(<https://github.com/dedoc/scramble>, <https://scramble.dedoc.co/installation>).
Правила валидации — краеугольный камень генерации: каждое правило
превращается в часть JSON Schema
(<https://scramble.dedoc.co/developers/validation-rules>).

Поддержка Laravel 13: v0.13.55 от 2026-11-16, требует
`illuminate/contracts ^10.0|^11.0|^12.0|^13.0`, `php ^8.1`
(<https://repo.packagist.org/p2/dedoc/scramble.json>). **Да, Laravel 13
поддерживается**, пакет обновлялся за 5 дней до этого исследования.

#### 4.2 Публикация по URL

После установки пакет сам регистрирует два маршрута
(<https://github.com/dedoc/scramble/blob/main/routes/web.php>):

```php
Scramble::registerUiRoute(path: 'docs/api')->name('scramble.docs.ui');
Scramble::registerJsonSpecificationRoute(path: 'docs/api.json')->name('scramble.docs.document');
```

- `/docs/api` — UI-просмотрщик;
- `/docs/api.json` — сам документ, `GET`, pretty-printed JSON.

По умолчанию доступ **только в `local`**: middleware
`RestrictedDocsAccess` пропускает запрос вне `local`, если разрешит
`Gate::define('viewApiDocs', ...)`, иначе `403`
(<https://github.com/dedoc/scramble/blob/main/src/Http/Middleware/RestrictedDocsAccess.php>).
Для требований карты (2.2) без «viewApiDocs» спека должна:

- либо закоммитить `api.json` в репозиторий и **не** открывать живой URL;
- либо разрешить `viewApiDocs` для всех (документ публичный), оставив
  `/docs/api.json` доступным из прода;
- либо сменить пути через `Scramble::ignoreDefaultRoutes()` и свои
  route-группы.

#### 4.3 CI-команда

`scramble:export` — самостоятельная artisan-команда, не требует
HTTP-сервера (`ExportDocumentation`):

```sh
php artisan scramble:export --path=api.json --fail-on-unknown
```

(`--path` — куда сохранить, по умолчанию `config('scramble.export_path')`
или `api.json`; `--stdout` — в stdout; `--api` — для не-`default` API;
`--fail-on-unknown` — вернуть non-zero, если сгенерировался
`UnknownType`, см. <https://github.com/dedoc/scramble/blob/main/src/Console/Commands/ExportDocumentation.php>).

Для контракта, который проверяет клиент, этого достаточно: CI сервера
экспортирует `api.json` и коммитит/артефактит; CI клиента скачивает этот
файл и сверяет свои модели. `--fail-on-unknown` — важная галочка: без неё
«не смогли вывести тип» молча превращается в `{}` в схеме, и контракт
перестаёт быть строгим.

#### 4.4 Scribe — и почему не он

`knuckleswtf/scribe` v5.11.0 (2026-06-08) требует
`laravel/framework ^9.21 || ^10.0 || ^11.0 || ^12.0 || ^13.0`
(<https://repo.packagist.org/p2/knuckleswtf/scribe.json>), то есть **Laravel
13 поддерживает**. Генерирует:

- HTML-документацию (в `laravel`-режиме — `/docs` из `scribe:generate`);
- `openapi.yaml` в `{static.output_path}/` (static) или
  `storage/app/scribe/openapi.yaml` (laravel); `laravel.add_routes = true`
  добавляет `/openapi.yaml`
  (<https://github.com/knuckleswtf/scribe-docs/blob/master/laravel/reference/10-config.md>);
- Postman-коллекцию;
- `.scribe/endpoints/*.yaml`, куда складывается результат и который
  **редактируется вручную**.

Генерация по коду у Scribe есть: `GetFromFormRequest` берёт `rules()`
([исходник](https://github.com/knuckleswtf/scribe/blob/master/src/Extracting/Strategies/BodyParameters/GetFromFormRequest.php),
[`GetFromFormRequestBase`](https://github.com/knuckleswtf/scribe/blob/master/src/Extracting/Strategies/GetFromFormRequestBase.php)),
но вывод в первую очередь документ для людей с примерами и описаниями;
OpenAPI — «opinionated spec, which doesn't cover all features of APIs in the
wild» (сама дока Scribe). Для контракта «источник правды, против которого
клиент валидирует модели» это лишний слой.

#### 4.5 Вердикт по OpenAPI

**Scramble**, потому что:

1. генерирует ровно то, что нужно — OpenAPI 3.1.0 JSON из валидации и
   типов ответов;
2. поддерживает Laravel 13 сегодня;
3. `scramble:export` работает в CI без HTTP;
4. есть готовый `security_strategy` для `auth:sanctum` — bearer-scheme
   добавляется в документ автоматически:
   `'security_strategy' => \Dedoc\Scramble\SecurityDocumentation\MiddlewareAuthSecurityStrategy::class`
   (<https://scramble.dedoc.co/usage/authentication>).

Оговорка: контракт клиента держится на том, что `uuid:4` попадает в схему
как `type: string, format: uuid`. Это одна из вещей, которую спека должна
закрепить тестом на сервере: «в api.json у `client_id` стоит
`format: uuid`» — тогда поломка генерации не пройдёт тихо.

### 5. Ретенция надгробий: планировщик, очередь, worker

#### 5.1 Нужен ли worker

**Нет.** Ретенция 30 дней — это один `DELETE` раз в сутки. Laravel 13
исполняет планировщик через одну cron-запись `schedule:run` каждую минуту;
`schedule:run` судит по серверному времени, пора ли задаче
(<https://github.com/laravel/docs/blob/13.x/scheduling.md#running-the-scheduler>).
Никаких воркеров для этого не нужно — команда выполняется в процессе
`schedule:run`, который завершается сам.

Очередь (`QUEUE_CONNECTION=database` в скелете, таблицы `jobs`/`failed_jobs`
уже мигрированы) понадобится, только если:

- чистка станет дольше, чем удобно держать `schedule:run` (сотни тысяч
  строк — нет);
- её захочется дёрнуть из HTTP-запроса и не ждать (не нужно);
- в будущем появятся рассылки/уведомления по почте.

Миграции для jobs уже есть в `web/database/migrations/0001_01_01_000002_create_jobs_table.php`,
дополнительно ничего не нужно.

#### 5.2 Регистрация расписания

Скелет имеет `routes/console.php` и **нет** `app/Console/Kernel.php`
(в Laravel 13 ядро консоли собирается через `bootstrap/app.php`). Расписание
живёт там же, где artisan-команды — в `routes/console.php`:

```php
use Illuminate\Support\Facades\Schedule;

Schedule::command('notes:purge-tombstones')->daily()->withoutOverlapping();
```

`Schedule::command()` — это фасад над `Schedule::command()` из
`Illuminate\Console\Scheduling\Schedule` (`Schedule.php:185`); `daily()`
взят из `ManagesFrequencies::daily()` = «в 00:00»
(`ManagesFrequencies.php:338`). `withoutOverlapping()` не строго нужен
(задача короче суток), но защищает от двойного запуска, если cron настроят
на двух машинах.

Альтернатива без отдельной команды — замыкание в `routes/console.php`:

```php
Schedule::call(fn () => Note::onlyTrashed()
    ->where('deleted_at', '<=', now()->subDays(30))
    ->forceDelete())->daily();
```

Документация использует ровно этот пример
(<https://github.com/laravel/docs/blob/13.x/scheduling.md#scheduling-artisan-commands>).
Для спеки лучше **именованная команда** (`php artisan notes:purge-tombstones`):
её можно запустить руками, протестировать и увидеть в `schedule:list`.

Сам пакет команд (`app/Console/Commands/PurgeTombstones.php`) лучше писать
**батчами**, потому что `forceDelete()` по запросу грузит все модели в
память:

```php
Note::onlyTrashed()
    ->where('deleted_at', '<=', now()->subDays(30))
    ->orderBy('id')
    ->chunkById(500, fn ($notes) => $notes->each->forceDelete());
```

#### 5.3 Что спека должна сказать о данных

- Чистка удаляет строки, у которых `deleted_at` старше 30 дней — считая от
  **серверного** `deleted_at`, а не от клиентского.
- После чистки повторный push «воскрешения» старой заметки создаст новую
  строку с тем же `client_id` (индекс позволяет — старой строки уже нет).
  Для «последняя запись побеждает» это нормальное поведение, но лучше его
  назвать в спеке явно.
- `withoutOverlapping()` и `onOneServer()` для синхронизации в спеке — не
  обязательны, но дешёвы; `onOneServer()` требует общего кеша. Скелет
  использует `CACHE_STORE=database`, так что `onOneServer()` заработает
  сразу.

### 6. Валидация UUID и позиций

#### 6.1 Правило `uuid`

`validateUuid()` (`vendor/laravel/framework/src/Illuminate/Validation/Concerns/ValidatesAttributes.php:2810`)
принимает необязательный параметр версии и вызывает `Str::isUuid($value, $version)`.
Без параметра — любая версия RFC 9562 (1, 3, 4, 5, 6, 7, 8); с `uuid:4` —
только v4. `Str::isUuid` без версии проверяет регуляркой каноническую запись
`8-4-4-4-12` **и разрешает верхний регистр**
(`Str::isUuid`, `vendor/.../Support/Str.php:687`). Для клиентских UUID4:

```php
$request->validate([
    'notes'                 => ['required', 'array', 'max:500'],
    'notes.*.client_id'     => ['required', 'uuid:4', 'regex:/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/'],
    'notes.*.text'          => ['present', 'string', 'max:65535'],
    'notes.*.position'      => ['present', 'numeric', 'between:-1e12,1e12'],
    'notes.*.updated'       => ['required', 'date'],
    'notes.*.deleted'       => ['boolean'],
]);
```

`uuid:4` + `regex` в нижнем регистре — намеренное дублирование: `uuid:4` —
семантическая проверка версии, `regex` — нормализация регистра, без которой
MySQL может создать на одну заметку две строки (см. §1.1). `numeric` для
`position`, а не `integer`: решение 2.2 — число, а дробь даёт вставку «между»
без пересчёта соседей, если позже понадобится.

#### 6.2 Гонки при вставке и обновлении (push)

Три уровня защиты, от лучшего к запасному:

1. **Контракт «upsert по `(user_id, client_id)`».** Приложение делает это
   через `Note::updateOrCreate(['user_id' => $uid, 'client_id' => $cid], [...])`.
   В Laravel 13 `updateOrCreate` → `firstOrCreate` → `createOrFirst`,
   `createOrFirst` ловит `UniqueConstraintViolationException` и повторяет
   `first()` под `writePdo`
   (`vendor/laravel/framework/src/Illuminate/Database/Eloquent/Builder.php:753-794`).
   Это значит, что даже при одновременном push двух устройств с одним
   `client_id` **дубля не будет**: один INSERT победит, второй получит
   unique-ошибку и превратится в второй `first()`+`save()`. **Но** `save()`
   второй транзакции пишет поверх первый — отсюда пункт 2.
2. **`lockForUpdate()` внутри транзакции.** Перед upsert-ом берём
   блокировку строки:

   ```php
   DB::transaction(function () use ($user, $incoming) {
       $note = Note::withTrashed()
           ->where('user_id', $user->id)
           ->where('client_id', $incoming['client_id'])
           ->lockForUpdate()
           ->first();

       if ($note && $note->server_updated_at && $incoming['server_updated_at'] < $note->server_updated_at) {
           return; // старая запись, игнорируем
       }
       // ... updateOrCreate / создание
   }, attempts: 3);
   ```

   Документация: `lockForUpdate` «предотвращает изменение выбранных записей
   и выбор с shared-локом» — обёртывать в транзакцию обязательно
   (<https://github.com/laravel/docs/blob/13.x/queries.md#pessimistic-locking>);
   `attempts: 3` — ретрай при deadlock
   (<https://github.com/laravel/docs/blob/13.x/database.md#handling-deadlocks>).
   Для LWT `server_updated_at = now()` — это единственная строка, которую
   защищает лок; **сериализация через `user_id`-строку — единственный
   кросс-СУБД-надёжный способ** (см. ниже).
   На пустой таблице (первый push) `lockForUpdate` ничего не блокирует
   — именно для этого оставлен пункт 1 (unique + `createOrFirst`).
3. **SQLite: «один писатель на базу».** `UPDATE` берёт блокировку записи на
   файл; второй писатель получит `database is locked`, если не выставить
   `busy_timeout`. Тестовая проверка на этой машине: PHP SQLite **3.43.2**;
   `PHP_CLI_SERVER_WORKERS=4` в `.env.example` уже прописан (раскомментирован
   он или нет — на проде нужен один процесс/php-fpm-пул с
   `DB_CONNECTION=sqlite` при нескольких словах-читателях не годится).
   Для продакшена спека должна выбрать **MySQL** или **SQLite с WAL +
   `busy_timeout`**:

   ```php
   // config/database.php, 'sqlite' => [...]
   'journal_mode' => env('DB_JOURNAL_MODE', 'wal'),
   'busy_timeout' => env('DB_BUSY_TIMEOUT', 5000),
   ```

   На MySQL — обычная InnoDB, без WAL: `lockForUpdate` на существующей
   строке делает эксклюзивную блокировку; на несуществующей — нет, поэтому
   пункты 1 и 2 идут вместе.

#### 6.3 Гонки при перестановке (order/position)

Решение 2.2 — `position` как число на заметке. Главная ловушка: **если
клиент шлёт только одну заметку с новым `position`, сервер может получить
две заметки с одинаковой позицией**, и порядок в списке станет
недетерминированным. Ещё хуже — race на переиндексации: два клиента
переставили разные заметки, и «сдвиг остальных на +1» пересчитался дважды.

Правила, которые надо зафиксировать в спеке:

1. **Перестановка — это не одиночный апдейт, а список.** При drag-and-drop
   клиент строит новый порядок локально и шлёт **все задетые** заметки
   (`PUT /api/sync/notes` с массивом `[{client_id, position, updated}]`).
   Сервер применяет их **в одной транзакции** после `lockForUpdate` по
   `user_id` (одна строка `users` как mutex):

   ```php
   DB::transaction(function () use ($user, $items) {
       // единый mutex на пользователя: все перестановки идут через него
       DB::table('users')->where('id', $user->id)->lockForUpdate()->first();

       foreach ($items as $item) {
           Note::updateOrCreate(
               ['user_id' => $user->id, 'client_id' => $item['client_id']],
               ['position' => $item['position'], 'server_updated_at' => now()],
           );
       }
   });
   ```

   На SQLite `lockForUpdate` игнорируется (нет `FOR UPDATE`), но там
   блокировка на запись всё равно сериализует транзакции — этого достаточно;
   на MySQL/Postgres строка `users` становится общей точкой сериализации
   перестановок (дешёво: перестановки редки).
2. **Позиции — монотонны и уникальны, если это возможно.** Уникальность
   `position` **нельзя** ставить в БД: при `LWT` две правки могут привести
   к одинаковой позиции, и unique-индекс превратит безобидный конфликт в
   ошибку 500. Вместо этого `orderBy('position')->orderBy('client_id')` —
   детерминированный tie-break.
3. **Клиент не пересчитывает чужие позиции.** Если клиент считает новой
   позицией «среднее между соседями», сервер обязан отвергать NaN/INF и
   значения вне диапазона (`between:-1e12,1e12`). Лучше — целочисленный
   пересчёт `position` на тысячи (`1000, 2000, 3000`) и вставка `1500` —
   работает без float-погрешностей и без пересчёта соседей.

---

## Что спека может цитировать прямо сейчас

- Миграция `notes`: `$table->unique(['user_id', 'client_id'])`,
  `$table->index(['user_id', 'server_updated_at'])`,
  `$table->softDeletesTz()`, `server_updated_at` с `precision: 6`.
- Модель: `use HasApiTokens, SoftDeletes;` `client_id` — строка в нижнем
  регистре, UUID4.
- Маршруты токена:
  - `POST /api/sync/tokens` (session) → `{token}` один раз;
  - `DELETE /api/sync/tokens` (Bearer) → отзыв текущего;
  - все `sync`-эндпоинты — `auth:sanctum`.
- Fortify для веба: `/login`, `/logout`, `/register` из пакета; вьюхи — свои
  Blade-файлы.
- Scramble: `/{docs/json}` из коробки, `php artisan scramble:export --path=api.json --fail-on-unknown`
  в CI.
- Планировщик: `Schedule::command('notes:purge-tombstones')->daily()` в
  `routes/console.php`; `* * * * * php artisan schedule:run` в crontab.
- Валидация UUID: `['required', 'uuid:4', 'regex:/^[0-9a-f]{8}-...$/']`.
- Перестановка: массив затронутых заметок в одной транзакции с
  `lockForUpdate` по `users.id`.

## Источники

**Локальный скелет `web/` (Laravel 13.43.0):**

- `web/composer.json` (`php ^8.3`, `laravel/framework ^13.17`),
  `composer.lock` (`v13.43.0`), `web/.env.example`
  (`DB_CONNECTION=sqlite`, `QUEUE_CONNECTION=database`,
  `SESSION_DRIVER=database`, `CACHE_STORE=database`).
- `web/database/migrations/0001_01_01_000000_create_users_table.php` —
  `users`, `password_reset_tokens`, `sessions`.
- `web/database/migrations/0001_01_01_000002_create_jobs_table.php` —
  `jobs`, `job_batches`, `failed_jobs` уже есть.
- `web/routes/console.php`, `web/bootstrap/app.php` — планировщик живёт в
  `routes/console.php` (в 13 нет `app/Console/Kernel.php`).
- `vendor/laravel/framework/src/Illuminate/Database/Schema/Blueprint.php`
  (`unique()`, `indexCommand()`, `softDeletes()`).
- `vendor/laravel/framework/src/Illuminate/Validation/Concerns/ValidatesAttributes.php:2810`,
  `vendor/laravel/framework/src/Illuminate/Support/Str.php:687`.
- `vendor/laravel/framework/src/Illuminate/Database/Eloquent/Builder.php:753-794`
  (`firstOrCreate`/`createOrFirst`/`updateOrCreate`).
- `vendor/laravel/framework/src/Illuminate/Console/Scheduling/ManagesFrequencies.php:338`,
  `Schedule.php:185` (`daily`, `command`).
- `config/database.php` (`sqlite`, `busy_timeout`, `journal_mode`).

**Документация Laravel 13.x:**

- <https://github.com/laravel/docs/blob/13.x/migrations.md>
- <https://github.com/laravel/docs/blob/13.x/eloquent.md>
- <https://github.com/laravel/docs/blob/13.x/sanctum.md>
- <https://github.com/laravel/docs/blob/13.x/fortify.md>
- <https://github.com/laravel/docs/blob/13.x/starter-kits.md>
- <https://github.com/laravel/docs/blob/13.x/scheduling.md>
- <https://github.com/laravel/docs/blob/13.x/validation.md>
- <https://github.com/laravel/docs/blob/13.x/database.md>
- <https://github.com/laravel/docs/blob/13.x/queries.md>
- <https://github.com/laravel/docs/blob/13.x/routing.md>

**Исходники пакетов:**

- Sanctum 4.x:
  <https://github.com/laravel/sanctum/blob/4.x/src/HasApiTokens.php>,
  <https://github.com/laravel/sanctum/blob/4.x/src/Guard.php>,
  <https://github.com/laravel/sanctum/blob/4.x/src/PersonalAccessToken.php>,
  <https://github.com/laravel/sanctum/blob/4.x/config/sanctum.php>,
  <https://github.com/laravel/sanctum/blob/4.x/database/migrations/2019_12_14_000001_create_personal_access_tokens_table.php>
- Fortify 1.x:
  <https://github.com/laravel/fortify/blob/1.x/routes/routes.php>,
  <https://github.com/laravel/fortify/blob/1.x/config/fortify.php>
- Breeze 2.x (устаревший):
  <https://github.com/laravel/breeze/blob/2.x/README.md>
- Scramble:
  <https://github.com/dedoc/scramble>,
  <https://github.com/dedoc/scramble/blob/main/routes/web.php>,
  <https://github.com/dedoc/scramble/blob/main/src/Http/Middleware/RestrictedDocsAccess.php>,
  <https://github.com/dedoc/scramble/blob/main/src/Console/Commands/ExportDocumentation.php>,
  <https://scramble.dedoc.co/installation>,
  <https://scramble.dedoc.co/usage/export>,
  <https://scramble.dedoc.co/usage/authentication>,
  <https://scramble.dedoc.co/developers/validation-rules>
- Scribe:
  <https://github.com/knuckleswtf/scribe/blob/master/src/Extracting/Strategies/BodyParameters/GetFromFormRequest.php>,
  <https://github.com/knuckleswtf/scribe-docs/blob/master/laravel/reference/10-config.md>,
  <https://github.com/knuckleswtf/scribe-docs/blob/master/laravel/1-getting-started.md>

**Версии и совместимость с Laravel 13 (Packagist API, 2026-11-21):**

- `dedoc/scramble` v0.13.55 (2026-11-16), `illuminate/contracts ^10–^13`
- `knuckleswtf/scribe` v5.11.0 (2026-06-08), `laravel/framework ^9.21–^13.0`
- `laravel/sanctum` v4.5.0 (2026-11-11), `illuminate/* ^12.0|^13.0`
- `laravel/fortify` v1.43.0 (2026-11-14), `illuminate/* ^12.0|^13.0`
- `laravel/breeze` v2.4.2 (2026-05-14), `illuminate/* ^11.0|^12.0|^13.0`
  — но README говорит «for Laravel 11.x and prior»
