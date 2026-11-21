# Research: схема хранения и синхронизации в Laravel

Type: research
Status: resolved
Blocked by:

## Question

Какие готовые механизмы Laravel 13 подходят для серверной части
синхронизации, чтобы спека опиралась на факты, а не на память.

Основные вопросы:

- **Схема БД**: как Laravel выражает композитный уникальный индекс
  (`user_id` + клиентский UUID), soft delete (`deleted_at`) и
  интервальные запросы (`where updated_at > ?`) в миграциях. Есть ли
  особенности для SQLite/MySQL.
- **Sanctum**: как выдавать API-токен устройства, как его отзывать, как
  ограничивать abilities и что попадает в `personal_access_tokens`.
- **Fortify vs Breeze**: что выбирают для «email + пароль + веб-сессии»
  в новом приложении Laravel 13, что ставится из коробки, где живут
  маршруты входа.
- **OpenAPI-генерация**: Scramble или Scribe для Laravel 13 — что
  генерирует спек по коду, как публиковать по URL, нужна ли отдельная
  команда в CI.
- **Очереди и фоновые задачи**: нужен ли Queue для ретенции надгробий
  (30 дней) — task scheduling (`Schedule::daily()`), миграции для
  jobs, готовые команды.
- **Валидация UUID и позиций**: `uuid` validation rule, как проверять
  порядок без гонок.

Ответ — отчёт с ссылками на первоисточники (документация Laravel 13,
исходники Sanctum/Fortify/Scramble) и с примерами миграций и маршрутов,
которые спека может цитировать напрямую.

## Answer

Отчёт: [05-laravel-storage.md](../research/05-laravel-storage.md).

Короткий вердикт. Всё нужное есть в Laravel 13 из коробки, кроме двух пакетов —
`laravel/sanctum` (токены устройств) и `laravel/fortify` (вход по email+паролю).
Схема выражается штатным Schema Builder: `$table->unique(['user_id', 'client_id'])`
для клиентского UUID4 (строкой в нижнем регистре, `string(36)`, не `uuid`),
`$table->softDeletesTz()` для `deleted_at`, индекс `(user_id, server_updated_at)`
для pull'а `WHERE server_updated_at > ?` (точность 6, `APP_TIMEZONE=UTC`).
Надгробия надо отдавать через `withTrashed()` и помнить, что `delete()` не
бампает `server_updated_at`. Sanctum хранит SHA-256 хеш токена, а не plaintext,
abilities — JSON; токен отзывается `currentAccessToken()->delete()`. Fortify, а не
Breeze: Breeze объявлен «для Laravel 11.x и ранее», а все стартер-киты 13 требуют
JS-фронтенд; маршруты `/login`, `/logout`, `/register` регистрирует сам пакет,
вьюхи пишем в Blade. Открытый спек — Scramble: OpenAPI 3.1.0 из кода, Laravel 13
поддерживается (v0.13.55), в CI `php artisan scramble:export --path=api.json
--fail-on-unknown`; Scribe тоже знает 13, но строит документ для людей и легко
рассинхронизируется с кодом. Ретенция надгробий — `Schedule::command(...)->daily()`
в `routes/console.php` + cron `schedule:run`, queue worker не нужен. Валидация —
`uuid:4` плюс `regex` на нижний регистр; перестановка позиций — массив задетых
заметок в одной транзакции с `lockForUpdate` по `users.id`, без unique-индекса
на `position`.
