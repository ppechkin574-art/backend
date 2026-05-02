# CLAUDE.md — контекст для будущих сессий

> Этот файл автоматически загружается Claude Code при открытии репозитория. Он содержит достаточно контекста, чтобы новая сессия могла сразу продолжить работу без повторного исследования кодовой базы.
>
> **Не удаляй этот файл и не сокращай — он экономит часы каждой следующей сессии.**

---

## TL;DR

Это **backend FastAPI** для образовательной платформы **AIMA / Lumi** (подготовка к ЕНТ Казахстана). Является одним из трёх репо проекта. Поднят на **Railway** 01.05.2026, API живой, миграции применены, контент Романа залит из дампа (12 предметов / 555 тем / 2821 вопрос). Авторизация через Keycloak работает, медиа-хранилище MinIO подключено и используется через переписанный `FileService`. Админ-панель работает в проде.

**Что осталось:** Firebase / Apple / Google OAuth / FreedomPay / SMS / Email — стоят заглушки, нужны реальные ключи.

**Текущие URL:**
- Backend API: `https://backend-production-f2a1.up.railway.app/docs`
- Admin Panel: `https://admin-production-4572.up.railway.app`
- Keycloak: `https://keycloak-production-0a0c.up.railway.app`
- MinIO Console: `https://minio-production-3f82.up.railway.app`

**Главный roadmap:** см. [TECH_DEBT.md](./TECH_DEBT.md). Документ ведётся параллельно с работой.

---

## Контекст проекта (3 репо)

| Репо | Стек | Назначение |
|---|---|---|
| **`ppechkin574-art/backend`** (этот) | FastAPI + SQLAlchemy 2 + Alembic + Postgres + Redis | API для мобильного приложения и админки |
| `ppechkin574-art/admin` | React 18 + TypeScript + Vite + Zustand + Keycloak | Админ-панель для контента и пользователей |
| `ppechkin574-art/app` | Flutter 3.41 + flutter_bloc + Dio + ObjectBox | Мобильное приложение для студентов |

**Связь:** мобильное приложение → REST API backend → PostgreSQL/Redis. Авторизация через Keycloak (OIDC). Платежи через FreedomPay. Push через Firebase.

**Владелец:** `ppechkin574-art` (PP, заказчик). Изначальный разработчик — Roman Vasilev (`romannvz`). Репозитории были перенесены к заказчику 01.05.2026 через `git push` с заменой remote — авторство коммитов сохранено за оригинальным автором (это нормально и юридически корректно, заказчик — владелец продукта).

---

## Текущее состояние Railway-стека

**Railway проект:** `content-inspiration → production`

### Сервисы (7 штук, все Active)

| Сервис | Источник | Назначение | URL |
|---|---|---|---|
| **backend** | GitHub `ppechkin574-art/backend` | FastAPI | `https://backend-production-f2a1.up.railway.app` |
| **admin** | GitHub `ppechkin574-art/admin` | React админ-панель | `https://admin-production-4572.up.railway.app` |
| **Postgres** | Railway template | основная БД backend | `postgres.railway.internal:5432` |
| **Redis** | Railway template | кеш + WS-токены + коды подтверждения | `redis.railway.internal:6379` |
| **keycloak** | Docker `quay.io/keycloak/keycloak:26.0` | OIDC-сервер | `https://keycloak-production-0a0c.up.railway.app` |
| **Keycloak** (Postgres) | Railway template | БД для Keycloak (имя сервиса конфликтует с основным — мнемоника) | приватная сеть |
| **minio** | Docker `minio/minio:latest` | S3-совместимое хранилище | `https://minio-production-3f82.up.railway.app` (Console). API через приватную сеть `minio.railway.internal:9000` |

### Что работает

- ✅ Build + deploy backend и admin через GitHub auto-deploy.
- ✅ Все миграции alembic применены (накатан полный путь до `bdab54e499a9`).
- ✅ FastAPI Swagger `/docs` отвечает, все endpoint'ы доступны.
- ✅ **Контент в БД:** 12 предметов, 555 тем, 2821 вопрос, 12042 варианта, 20105 question_blocks (залит из дампа Романа `main_db_backup_040226.dump`).
- ✅ **Keycloak**: realm `lumi`, клиенты `web-app` (confidential) и `tesla-admin-panel` (public+PKCE), роли `admin`/`user`, тестовый юзер `admin@aima.kz` логинится через `/auth/login-swagger`.
- ✅ **MinIO**: bucket `aima-uploads`, отдельный service account с restricted policy. `FileService` переписан на MinIO (`open(file, "wb")` → `MediaStorageClientMinio.save()`). При загрузке аватара/картинки предмета файл реально попадает в bucket.
- ✅ **Admin-панель** видит все данные, разделы Предметы / Темы / Вопросы / Тренажёры / ENT / Промокоды / Связки / Модули / Учителя / Пробное ЕНТ — все открываются.
- ✅ Telegram-клиент инициализирован (заглушка токена, alerts молча падают).
- ✅ FreedomPay payment poller запущен (реальных merchants нет).
- ✅ WebSocket heartbeat работает.
- ✅ CORS preflight (`OPTIONS`) корректно отвечает 200 для админ-домена.
- ✅ Endpoint `/admin/cache/flush` для сброса Redis-кеша после массовых изменений в БД.

### Что отключено / стоит как заглушка

| Интеграция | Статус | Причина |
|---|---|---|
| ✅ **Email (Resend)** | **Подключено**, отправка с `noreply@aima.kz`, домен Verified | API key `re_6FFUejgK_...` в Railway. Шаблон письма ещё содержит брендинг Lumi — фикс в TECH_DEBT 7a |
| ✅ **SMS (SMSC.kz)** | **Подключено**, в DEBUG-режиме (бесплатно, код пишется в Deploy Logs) | Login `aima_app`, отдельный API-пароль. Для прода — пополнить баланс + снять `SMSC__DEBUG=true` + зарегистрировать sender `AIMA` |
| Firebase Cloud Messaging | ❌ `firebase__enabled=false` | Нет credentials JSON в volume |
| Apple Sign-In | ❌ заглушки | Нет `.p8` ключа от Apple Developer |
| Google OAuth | ❌ `changeme` | Нет client_id/secret из Google Cloud Console |
| FreedomPay | ❌ `merchant_id=000000`, `secret=changeme` | Нет договора с банком |
| Wazzup (WhatsApp) | ❌ `changeme` | Нет API-ключа |
| Telegram-бот для алёртов | ❌ `changeme` | Нет токена @BotFather |
| Cloudflare CDN | ❌ `changeme` | Не используется |

### Email — почему Resend, а не Gmail

**Railway блокирует исходящий SMTP-трафик** (порты 25/465/587). Любой SMTP-клиент будет получать `OSError: [Errno 101] Network is unreachable`. Это политика большинства cloud-провайдеров против спама — изменить нельзя.

Решение: **HTTP API сервис** вместо SMTP. Выбран **Resend** (3000 писем/мес бесплатно). Старый `PersonalGmailClient` через `smtplib.SMTP_SSL` переписан на `ResendEmailClient` через `httpx.post(api.resend.com/emails)`. Алиас `PersonalGmailClient = ResendEmailClient` сохранён для backward compat. См. коммит `a181b41`.

**Domain setup:** в Resend Dashboard добавлен `aima.kz` (root domain). DNS-записи (DKIM TXT на `resend._domainkey.aima.kz`, SPF TXT на `send`, MX на `send`) добавлены в Hoster.kz. Verified за 5 минут. Поддомен `send.aima.kz` нужен для bounce-обработки, но FROM шлётся с **`noreply@aima.kz`** (главный домен — там DKIM-ключ).

### SMS — почему SMSC.kz

Изначально в коде Романа клиент `SMSCClient` ходит на `https://smsc.kz/rest/`. Не альтернатива — встроенный выбор. Разумный для KZ-рынка:
- Местный провайдер с прямыми контрактами с Beeline/Kcell/Tele2/Activ.
- Цена ~5-8 ₸/SMS (vs ~32 ₸ через Twilio).
- Регистрация Sender ID `AIMA` за 1-3 дня (Twilio требует Brand registration $40 + 4-6 недель).
- Документация на русском.

Минусы: дешёвая надёжность (~95% доставка, бывают потери), нет WhatsApp. На проде когда выйдем за пределы KZ — стоит мигрировать на Twilio (записал в TECH_DEBT).

### Тестовые креды

- **Keycloak admin** (для самого Keycloak): `admin` / `<KEYCLOAK_ADMIN_PASSWORD>` (в Variables сервиса `keycloak`).
- **App admin** (для backend/admin-panel через Keycloak realm `lumi`): `admin@aima.kz` / `ChangeMeAdmin123!` (temporary; при первом логине через Account Console попросит сменить).
- **Mobile test user** (Keycloak realm `lumi`): `+77001234567` / `Test12345!` — для логина по номеру в Flutter-приложении.
- **MinIO Console root**: `aima_admin` / `Aima2026MinioStrongPassXyz`.
- **MinIO Service Account для backend** (используется в env): Access Key `8DIGUUC4A3ZZTTFNDTV1`, Secret Key хранится в Railway Variables `minio__secret_key`.
- **Postgres** для backend: connection string в `${{Postgres.DATABASE_URL}}` (внутр.) или `DATABASE_PUBLIC_URL` (публ., через `switchyard.proxy.rlwy.net`).
- **Resend API**: `re_6FFUejgK_5yL5eP3GMDRMBeZJUFzRurut` (в `email_client__API_KEY`). Привязан к `ppechkin574@gmail.com`. Domain `aima.kz` Verified. Регион Tokyo (ap-northeast-1).
- **SMSC.kz**: `aima_app` / отдельный API-пароль `b2F9b7H3a5K0x1W0`. Sender пока `SMSC.KZ` (стандартный, для прода зарегистрировать `AIMA`). Баланс 0 ₸ — реальные SMS не уходят, только DEBUG-симуляция.

### Структура проекта в Railway

```
content-inspiration / production
│
├── backend          ← GitHub auto-deploy
│   ↓ database__URI=${{Postgres.DATABASE_URL}}
│   ↓ REDIS_URL=...
│   ↓ keycloak__open_id__SERVER_URL=https://keycloak-production-0a0c....
│   ↓ minio__endpoint=minio.railway.internal:9000
│
├── admin            ← GitHub auto-deploy (build-time VITE_* env)
│   ↓ VITE_API_BASE_URL → backend
│   ↓ VITE_KEYCLOAK_URL → keycloak
│
├── Postgres         ← основная БД
├── Redis            ← кеш
├── Keycloak         ← Postgres-БД для Keycloak (имя путает; мнемоника)
├── keycloak         ← Docker, Keycloak server
└── minio            ← Docker, S3-совместимое хранилище (volume /data)
```

См. **[TECH_DEBT.md](./TECH_DEBT.md)** — roadmap по фазам и подробный список оставшихся секретов.

---

## Что было сломано в исходном репо (важно при отладке)

Когда репо принесли заказчику, Dockerfile **не собирался**, миграции **не накатывались**, ряд DTO падали на пустых полях. Все исправления — в коммитах между `7feb550` и `a998c9d`. Если появятся регрессии — смотреть туда.

### Сборка и инфраструктура

| Проблема | Файл | Коммит фикса |
|---|---|---|
| Не было `requirements.txt` (только конфиги ruff/vulture в `pyproject.toml`) | сгенерирован из импортов | `7feb550` |
| `*.txt` в `.gitignore` блокировал `requirements.txt` | `.gitignore` (добавил `!requirements.txt`) | `7feb550` |
| Dockerfile не ставил `gcc`/`libpq-dev`/`libpq5` | `Dockerfile` | `eeac961` |
| `src/main.py` хардкодил порт 8000, игнорировал `$PORT` от Railway | `src/main.py` | `eeac961` |
| Не было `email-validator` (нужен для `pydantic.EmailStr` в `KeycloakUserDTO`) | `requirements.txt` | `f298161` |

### Миграции БД

| Проблема | Файл | Коммит фикса |
|---|---|---|
| Миграция `fc858cd71edc_migration_fix.py` создавала UNIQUE на закомментированных колонках `guid` | раскомментировал 5 `add_column` | `b8b3f04` |
| Миграция `420aa383195e_*.py` ссылалась на `students.guid` (колонка называется `id`) | заменил `["guid"]` → `["id"]` | `f95e4d5` |
| Наша миграция `d1f2a8c4e5a0_add_subject_image.py` дублировала колонку `subjects.image` (она уже есть в дампе Романа) | удалена | `ae83bf3` |

### Авторизация и DTO

| Проблема | Файл | Коммит фикса |
|---|---|---|
| `KeycloakUserDTO.createdTimestamp/emailVerified/enabled` обязательны, но Admin API их не возвращает для realm-imported юзеров | сделал опциональными | `ee6fe50` |
| `UserDTO.created_at/updated_at` обязательны, но из Keycloak приходит `None` → 401 при `allow_only_admins` | сделал опциональными | `be8daa6` |
| `allow_only_admins` оборачивал любую ошибку в общий `Authentication system error`, скрывая реальную причину | добавил `logger.exception` + детали типа в текст 401 | `b7e36e1` |
| `AppleOAuthClient.__init__` синхронно читал `apple_private_key.p8` при старте → краш если файла нет | сделал ленивым через `_load_private_key()` | `5cce03b` |

### CORS и медиа

| Проблема | Файл | Коммит фикса |
|---|---|---|
| `CORSMiddleware` добавлялся первым → становился самым внутренним → 400 на preflight | переместил в outermost | `24630ed` |
| Если `allowed_origins=*` — credentials=True блокировал CORS | переключаемый режим: `*` → `allow_origin_regex=".*"` + `credentials=False` | `a5308af` |
| `FileService` сохранял аватары и subject-images через `open(file, "wb")` на локальный диск контейнера (на Railway без volume → файлы пропадают при рестарте) | переписан на `MediaStorageClientMinio.save()` / `link()` / `remove()` | `ecca173` |
| `app.mount("/uploads", StaticFiles)` — больше не нужен после MinIO | удалён | `ecca173` |

### Кеширование

| Проблема | Файл | Коммит фикса |
|---|---|---|
| Redis-кеш с TTL 7 дней содержал stale `data:[]` после массового изменения БД (накат дампа) → questions/topics возвращали пусто | добавил `POST /admin/cache/flush` и `POST /admin/cache/invalidate` | `a998c9d` |

### Email и SMS интеграции

| Проблема | Файл | Коммит фикса |
|---|---|---|
| Изначальный `PersonalGmailClient` через `smtplib.SMTP_SSL` не работает на Railway (cloud-провайдеры блокируют исходящий SMTP) | переписал на `ResendEmailClient` через HTTP API `httpx.post(api.resend.com)` | `a181b41` |
| После замены `EmailClientSettings` старые SMTP-переменные в env (`SMTP_SERVER`, `PASSWORD`, `PORT`, `EMAIL`) роняли pydantic с `Extra inputs are not permitted` | добавил `model_config = SettingsConfigDict(extra="ignore")` | `b3116ac` |
| В `sms_client.py` Романа было `result["id", "N/A"]` — это передаёт **tuple** как ключ → `KeyError` даже в DEBUG-режиме | заменил на `result.get("id", "N/A")` (2 места) | `ef5101c` |

### Накат контента из дампа Романа

`main_db_backup_040226.dump` (7.1 MB, 4 февраля 2026) применили через psql:
1. `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` (сбросили нашу пустую схему).
2. `psql -f main_db_backup_040226.dump` — накатили все таблицы и данные.
3. Внутри дампа `alembic_version=ef87741a964d`. Сделали `UPDATE alembic_version SET version_num='ef87741a964d';` (ранее мы вручную поставили `d1f2a8c4e5a0` — это сбило alembic).
4. Backend пересобрался с удалённой миграцией `d1f2a8c4e5a0` → alembic накатил **3 недостающие миграции**: `a43fc4cdc2f0` (modules), `9c8edd56088b` (cashback), `bdab54e499a9` (bank).
5. Сбросили Redis-кеш через `/admin/cache/flush` — после этого админка показала весь контент.

⚠️ **Если придётся накатывать дамп повторно** в будущем — порядок шагов зафиксирован в `TECH_DEBT.md`. Очень важно сбросить Redis-кеш в конце.

---

## Архитектура backend

### Технологии

- **FastAPI** 0.115 + **uvicorn** 0.32 (синхронный, не async)
- **SQLAlchemy 2.0** + **Alembic** (32 миграции) + **psycopg2-binary** (синхронный драйвер!)
- **Pydantic 2.10** + **pydantic-settings** (с `env_nested_delimiter="__"`)
- **Redis** (кеш, WebSocket-токены, коды подтверждения)
- **dependency-injector** 4.43 (IoC-контейнер)
- **python-keycloak** 4.7 (OAuth2/OIDC клиент)
- **prometheus-client** (метрики на `/metrics`)
- **firebase-admin**, **minio**, **google-auth**

### Слои `src/`

```
src/
├── api/                    — FastAPI слой
│   ├── routes/             — эндпоинты, разделены: admin/, auth/, user/, payments/, analytics/, quiz/, promocodes/
│   ├── containers.py       — DI-контейнер (dependency-injector)
│   ├── dependencies.py     — Depends-провайдеры (get_user, get_auth_service, allow_only_admins)
│   ├── lifespan.py         — startup: payment poller, WS heartbeat, daily test scheduler
│   ├── exceptions/         — handlers (RequestValidationError, HTTPException)
│   └── middlewares/        — ExceptionLoggingMiddleware (Telegram alerts), LoggingContextMiddleware
│
├── auth/                   — Keycloak-based аутентификация
│   ├── services.py         — AuthService (register, login, OAuth, confirmation codes)
│   ├── repositories/       — UserRepositoryKeycloak (HTTP), ConfirmationCodeRepositoryRedis
│   ├── oauth_helper.py     — Google/Apple OAuth интеграция
│   └── admin_service.py    — управление юзерами через Keycloak Admin API
│
├── quiz/                   — ЯДРО учебного контента
│   ├── models/             — Subject, Topic, Question, Variant, Hint, Trainer, EntOption,
│   │                          EntAttempt, DailyTest, AttendanceStreak, Cashback, Progress
│   ├── services/           — Question, Trainer, EntAttempt, DailyTest, Attendance,
│   │                          Statistic, Progress, ModuleLesson services
│   ├── repositories/       — Repository для каждой сущности
│   ├── uows/uows.py        — UnitOfWorkTests, UnitOfWorkQuestions
│   ├── parsers/            — QuestionParserXLSX (импорт из Excel)
│   └── dtos/               — Service DTOs
│
├── payments/               — FreedomPay интеграция
│   ├── services.py         — PaymentService
│   ├── models.py           — Payment, PaymentStatusHistory
│   ├── ws_tokens.py        — WebSocketTokenManager (TTL=600с)
│   └── webhook.py          — приём callback от FreedomPay (HMAC-MD5 подпись)
│
├── subscription/           — подписки FREE/LITE/PRO
│   ├── models.py           — SubscriptionPlan, Subscription, SubscriptionHistory
│   └── service.py          — проверка активности, обновление статуса
│
├── promocodes/             — промокоды (создание, валидация, история активаций)
├── bank/                   — виртуальный банк (CardStyle, UserBankAccount, Transaction, WithdrawalRequest)
├── analytics/              — UserActivity (events, JSONB meta, geo-данные)
├── student/                — Student (id UUID, rating), LastRatedTrainerAttemptId
│
├── clients/                — внешние сервисы
│   ├── identity_provider/  — IdentityProviderClientKeycloak
│   ├── freedom_pay/        — FreedomPayClient + poller.py (фоновый опрос статусов)
│   ├── notification/       — Email, SMS (SMSC), WhatsApp (Wazzup), Telegram
│   ├── firebase/           — Firebase push
│   ├── apple/, google/     — OAuth клиенты (Apple .p8, Google id_token)
│   └── media_storage/      — MediaStorageClientMinio (S3-совместимый)
│
├── database/               — sessionmaker, UoW база (синхронный SQLAlchemy)
├── common/                 — enums (PlanType, SubscriptionStatus, QuestionType, Difficulty, ExamType)
├── utils/
│   ├── cache.py            — CacheService(Redis), стратегии GLOBAL/USER, @cached декоратор
│   │                          + flush_all() / invalidate_by_resource() для админ-операций
│   ├── monitoring.py       — JsonFormatter, Prometheus метрики, LoggingContextMiddleware
│   └── file_service.py     — загрузка/выдача файлов через MinIO (S3-совместимое хранилище)
│
└── settings.py             — главная Pydantic-настройка (env_nested_delimiter="__")
```

### DI-контейнер (`src/api/containers.py`)

Паттерн `dependency-injector.DeclarativeContainer`. Регистрирует **синглтоны** для:
- Settings, Redis, Database, CacheService, FileService
- Все клиенты (Keycloak, Firebase, Email, SMS, Google/Apple OAuth, Wazzup)
- Все сервисы (AuthService, PaymentService, SubscriptionService, AttendanceService, QuestionService и др.)
- UoW: UnitOfWorkTests, UnitOfWorkQuestions

**Wiring:** `WiringConfiguration(packages=["api"])` — провайдеры доступны в `Depends(Provide[Container.x])`.

### API-роуты — разделение по ролям

| Префикс | Authentication | Файлы |
|---|---|---|
| `/auth/*` | публично | `src/api/routes/auth/` |
| `/user/*` | `Depends(get_user)` | `src/api/routes/user/` |
| `/payment/*` | `Depends(get_user)` | `src/api/routes/payments/` |
| `/promocodes/*` | `Depends(get_user)` | `src/api/routes/promocodes/` |
| `/admin/*` | `Depends(allow_only_admins)` (роль `admin` в Keycloak) | `src/api/routes/admin/` (subjects, topics, questions, ents, trainers, modules, statistics, dashboard, notifications, promocodes, users, bank, **cache**, subject_combinations) |
| `/analytics/*` | varies | `src/api/routes/analytics/` |
| `/health`, `/ready`, `/metrics` | публично | `src/api/routes/system.py` |
| `/ws/payment/{order_id}` | WS-токен через query param | `src/api/routes/payments/websocket_routes.py` |

**Новые admin-endpoint'ы (наши):**
- `POST /admin/cache/flush` — полностью очищает Redis. Использовать после массового изменения БД (импорт вопросов, накат дампа).
- `POST /admin/cache/invalidate` — точечная инвалидация по списку ресурсов (`subjects`, `topics`, `questions` и т.д.).

### Lifespan (startup tasks)

`src/api/lifespan.py` запускает:
1. **FreedomPay payment poller** — `clients/freedom_pay/poller.py`, опрос статусов каждые N сек.
2. **WebSocket heartbeat** — `ConnectionManager.start_heartbeat()`, пинг клиентам каждые 30 сек.
3. **Daily Test Notification Scheduler** — отправка push о новых тестах (отключён, если `firebase__enabled=false`).

### Repository / UoW pattern

Контекст-менеджеры:
```python
with uow:                      # __enter__ создаёт сессию
    questions = uow.questions.list()
    uow.commit()               # __exit__ commit/rollback
```

UoW классы: `UnitOfWorkSQLAlchemy` (база) → `UnitOfWorkTests` (quiz домен), `UnitOfWorkQuestions`, `UnitOfWorkAnalytics`, `UnitOfWorkStudents`.

### Settings — вложенные через `__`

`src/settings.py` использует `env_nested_delimiter="__"`. Например `KEYCLOAK__ADMIN__SERVER_URL` → `settings.keycloak.admin.server_url`.

Главный класс `Settings` объединяет: `redis_url`, `telegram_bot`, `keycloak`, `database`, `freedom_pay`, `google_oauth`, `apple_oauth`, `email_client`, `smsc`, `firebase`, `wazzup`, `minio`, `upload_base_dir`, `file_base_url`, `cloudflare_customer_code`, `allowed_origins`.

### Ключевые модели по доменам (для быстрой ориентации)

- **Quiz:** `Subject`, `Topic`, `Question`, `Variant`, `Hint`, `Trainer`, `TrainerAttempt`, `EntOption`, `EntAttempt`, `DailyTest`, `AttendanceStreak`, `Cashback`, `UserQuestionProgress`, `UserLessonProgress`, `UserModuleProgress`, `EntSubjectCombination`.
- **Payments:** `Payment`, `PaymentStatusHistory`.
- **Subscription:** `SubscriptionPlan` (FREE/LITE/PRO), `Subscription`, `SubscriptionHistory`.
- **Promocodes:** `Promocode`, `PromocodeUsage`.
- **Bank:** `CardStyle`, `UserBankAccount`, `Transaction`, `WithdrawalRequest`.
- **Analytics:** `UserActivity` (event_name, platform, app_version, country/city, lat/lng, meta JSONB).
- **Student:** `Student` (id UUID, rating), `LastRatedTrainerAttemptId`.
- **Auth:** **в БД нет** — пользователи в Keycloak, коды подтверждения в Redis.

### Кеширование

`src/utils/cache.py`. Стратегии:
- `CacheStrategy.GLOBAL` → ключ `:global:resource:params`
- `CacheStrategy.USER` → ключ `:user:user_id:resource:params`

Декоратор `@cached(strategy, ttl, resource)`. Default TTL — 3600 сек. Кешируются вопросы, тренеры, темы, статистика.

### Логирование

`src/utils/monitoring.py`. JSON-формат (JsonFormatter) → stdout. Поля: `timestamp`, `level`, `logger`, `message`, `module`, `function`, `line`, `props`, `exception`. `LoggingContextMiddleware` инжектит `request_id`, `user_id`, `client_ip`, `method`, `endpoint` в каждый лог.

Prometheus метрики на `/metrics`: `lumiapp_requests_total`, `lumiapp_request_duration_seconds`, `lumiapp_errors_total`.

### Главный entry point

```
src/main.py:
  app = create_app()
  if __name__ == "__main__":
      uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

src/api/__init__.py — create_app():
  setup logging → init Container → init_resources → FastAPI(lifespan)
  → middleware (CORS, LoggingContext, ExceptionLogging)
  → exception handlers → mount /uploads → include all routers
```

---

## Полезные навигационные ссылки

| Что нужно | Куда смотреть |
|---|---|
| Добавить env-переменную | `src/settings.py` + одна из `src/clients/*/settings.py` |
| Новый эндпоинт клиента | `src/api/routes/user/` |
| Новый эндпоинт админки | `src/api/routes/admin/` (не забыть `Depends(allow_only_admins)`) |
| Зарегистрировать новый клиент / сервис | `src/api/containers.py` |
| Добавить миграцию | `alembic revision --autogenerate -m "..."` (внутри контейнера) |
| Понять как работает X | искать в соответствующем домене (`src/quiz/`, `src/payments/` и т.д.) |
| Health check | `GET /health` |
| Swagger | `GET /docs` |

---

## Как продолжать работу

### При начале новой сессии

1. **Прочитай этот файл и [TECH_DEBT.md](./TECH_DEBT.md).** Этого достаточно для входа в контекст.
2. **Проверь что в Railway всё ещё крутится:** `https://backend-production-f2a1.up.railway.app/docs` должен открываться.
3. **Спроси юзера, на каком пункте roadmap'а остановились** или что нужно делать дальше.

### Известные ограничения окружения

- **Платформа:** Windows 10, PowerShell. Используй PowerShell-синтаксис, не bash-only.
- **Working directory у юзера:** обычно `C:\Users\usera`. Клон backend хранится в `C:\Users\usera\AppData\Local\Temp\aima-analysis\backend\`.
- **GitHub login:** `ppechkin574-art` через `gh` CLI, токен с правами `repo`. Все три репо (`backend`, `admin`, `app`) — приватные под этим аккаунтом.
- **Не использовать `git -i`/`git rebase -i`** — нет интерактивного TTY.
- **Email юзера:** `ppechkin574@gmail.com`.

### Соглашения по коммитам

Стиль которым уже пишутся коммиты в этой репе:
- `build: ...` — изменения сборки/зависимостей
- `fix: ...` — исправления багов
- `docs: ...` — документация
- `feat: ...` — новая функциональность

При коммитах **не использовать `--no-verify`**, **не амендить** существующие коммиты — всегда новый коммит. Перед `git commit` обязательно указывать `-c user.name="ppechkin574-art" -c user.email="ppechkin574@gmail.com"` (потому что Windows-окружение может подставить локального юзера).

### Что НЕ ломать

- **Авторство существующих коммитов** — пусть остаётся за `Roman Vasilev`. Не делать `git filter-repo`, `--reset-author` и подобное.
- **`alembic_version`** — после применения миграций НЕ удалять и не сбрасывать без явного согласия юзера, даже если БД пустая.
- **`.env` файлы** — не коммитить никогда. В `.gitignore` уже стоит, не трогать.
- **`secrets/*.p8`, `secrets/*.json`** — никогда в репо.
- **Контент в Postgres** (subjects/topics/questions из дампа Романа) — не дропать, не очищать без надобности. Снэпшот единственный, бэкапов в Railway пока нет.

### Стандартные операции

#### Подключение к Postgres через psql (с локального Windows)

```powershell
psql "postgresql://postgres:aFsRkzGZFajptqkLkMGystWMInIPgiqn@switchyard.proxy.rlwy.net:47781/railway"
```

URL берётся из Railway → `Postgres → Variables → DATABASE_PUBLIC_URL`. Пароль может смениться при ротации.

#### Подключение к Redis через Railway CLI

```powershell
npx -y @railway/cli link    # выбрать content-inspiration / production / Redis
npx -y @railway/cli ssh     # требует SSH ключ в ~/.ssh/
```

Альтернатива — через публичный URL: `Redis → Variables → REDIS_PUBLIC_URL` + локальный `redis-cli`.

#### Сброс кеша Redis после массового изменения данных

```bash
curl -X POST https://backend-production-f2a1.up.railway.app/admin/cache/flush \
     -H "Authorization: Bearer <admin_access_token>"
```

Или через Swagger (`/docs` → `POST /admin/cache/flush`). Делать **обязательно** после:
- импорта пакета вопросов (xlsx)
- наката нового дампа БД
- массового редактирования через админку

#### Залив дампа БД заново (если придётся)

```powershell
# 1. Очистить схему
psql "<DATABASE_PUBLIC_URL>" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO postgres;"

# 2. Накатить дамп
psql "<DATABASE_PUBLIC_URL>" -f main_db_backup_040226.dump

# 3. Установить alembic_version на ту, что в дампе
psql "<DATABASE_PUBLIC_URL>" -c "UPDATE alembic_version SET version_num='ef87741a964d';"

# 4. Restart backend (Railway автоматически накатит недостающие миграции)
# 5. Сбросить Redis-кеш через /admin/cache/flush
```

#### Управление MinIO bucket через mc.exe

```powershell
cd $env:USERPROFILE\Downloads
.\mc.exe alias set aima https://<minio-public-domain> aima_admin <root_password>
.\mc.exe ls aima/aima-uploads/                    # список файлов
.\mc.exe cp local-file.png aima/aima-uploads/...  # загрузить файл
```

Public domain MinIO (для mc) можно временно переключить на порт 9000 в Railway → Networking, затем вернуть на 9001.

---

## Контакты и зоны риска

- **Roman Vasilev** (`romannvz`) — изначальный разработчик. На момент 01.05.2026 ответил кратко («через docker?» и т.п.) — было разъяснено что развёрнуто на Railway. Авторские коммиты сохранены за ним.
- **Юридический статус:** заказчик утверждает, что код полностью его. Внешние ключи (Keycloak realm `lumi`, Firebase project `lumi-60282`, FreedomPay merchant) — у Романа. Заказчику нужно пересоздавать всё с нуля под свои аккаунты — это и есть смысл TECH_DEBT.md Фазы 3.

---

_Файл создан 01.05.2026. Последнее существенное обновление — 01.05.2026 после деплоя всех сервисов и наката контента. Обновляй при существенных изменениях архитектуры или появлении нового долгосрочного контекста._
