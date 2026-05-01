# CLAUDE.md — контекст для будущих сессий

> Этот файл автоматически загружается Claude Code при открытии репозитория. Он содержит достаточно контекста, чтобы новая сессия могла сразу продолжить работу без повторного исследования кодовой базы.
>
> **Не удаляй этот файл и не сокращай — он экономит часы каждой следующей сессии.**

---

## TL;DR

Это **backend FastAPI** для образовательной платформы **AIMA / Lumi** (подготовка к ЕНТ Казахстана). Является одним из трёх репо проекта. Поднят на **Railway** 01.05.2026, API живой, миграции применены. Все внешние интеграции (Keycloak, MinIO, Firebase, Apple, Google, FreedomPay, SMSC, Wazzup, Telegram) сейчас стоят с **заглушками** — нужно подменять на реальные ключи.

**Текущий URL:** `https://backend-production-f2a1.up.railway.app`

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

## Текущее состояние backend на Railway

**Railway проект:** `content-inspiration → production`

**Сервисы в проекте:**
- **`backend`** — этот репозиторий, auto-deploy с GitHub `main`.
- **`Postgres`** (railway template `postgres-ssl:18`) — основная БД, имя сервиса `Postgres` (с большой буквы).
- **`Redis`** — кеш и очереди.

**Что работает:**
- ✅ Build + deploy через Dockerfile.
- ✅ Все 32 alembic-миграции применены (после фиксов — см. ниже).
- ✅ FastAPI на `/docs` отвечает.
- ✅ Telegram-клиент инициализирован (с заглушкой токена — алерты не отправляются).
- ✅ FreedomPay payment poller запущен (но реальных платежей нет).
- ✅ WebSocket heartbeat работает.

**Что отключено / стоит как заглушка:**
- ❌ Firebase: `firebase__enabled=false` → push не отправляются.
- ❌ Keycloak `https://example.com` → логин невозможен.
- ❌ MinIO `localhost:9000` → загрузка файлов сломана.
- ❌ Все OAuth (Apple, Google) → социальный логин не работает.
- ❌ Email/SMS/WhatsApp → коды подтверждения не доходят.

См. **[TECH_DEBT.md](./TECH_DEBT.md)** — там roadmap по фазам и подробный список 32 секретов.

---

## Что было сломано в исходном репо (важно при отладке)

Когда репо принесли заказчику, Dockerfile **не собирался**, миграции **не накатывались**. Эти проблемы уже исправлены в коммитах `eeac961` … `f95e4d5`. Если появятся регрессии — смотреть туда.

| Проблема | Файл | Коммит фикса |
|---|---|---|
| Не было `requirements.txt` (только конфиги ruff/vulture в `pyproject.toml`) | сгенерирован из импортов | `7feb550` |
| `*.txt` в `.gitignore` блокировал requirements | `.gitignore` (добавил `!requirements.txt`) | `7feb550` |
| Dockerfile не ставил `gcc`/`libpq-dev`/`libpq5` | `Dockerfile` | `eeac961` |
| `src/main.py` хардкодил порт 8000, игнорировал `$PORT` от Railway | `src/main.py` | `eeac961` |
| Не было `email-validator` (нужен для `pydantic.EmailStr` в `KeycloakUserDTO`) | `requirements.txt` | `f298161` |
| Миграция `fc858cd71edc_migration_fix.py` создавала UNIQUE на закомментированных колонках `guid` | раскомментировал 5 `add_column` | `b8b3f04` |
| Миграция `420aa383195e_*.py` ссылалась на `students.guid` (колонка называется `id`) | заменил `["guid"]` → `["id"]` | `f95e4d5` |

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
│   ├── monitoring.py       — JsonFormatter, Prometheus метрики, LoggingContextMiddleware
│   └── file_service.py     — загрузка/выдача файлов
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
| `/admin/*` | `Depends(allow_only_admins)` (роль `admin` в Keycloak) | `src/api/routes/admin/` |
| `/analytics/*` | varies | `src/api/routes/analytics/` |
| `/health`, `/ready`, `/metrics` | публично | `src/api/routes/system.py` |
| `/ws/payment/{order_id}` | WS-токен через query param | `src/api/routes/payments/websocket_routes.py` |

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

---

## Контакты и зоны риска

- **Roman Vasilev** (`romannvz`) — изначальный разработчик. На момент 01.05.2026 не отвечает (в дороге). Заказчик объявил себя владельцем, но если Roman вернётся — могут быть вопросы. **Не делать ничего деструктивного** в репо до синхронизации.
- **Юридический статус:** заказчик утверждает, что код полностью его. Внешние ключи (Keycloak realm `lumi`, Firebase project `lumi-60282`, FreedomPay merchant) — у Романа. Заказчику нужно пересоздавать всё с нуля под свои аккаунты — это и есть смысл TECH_DEBT.md фазы 2-3.

---

_Файл создан 01.05.2026. Обновляй при существенных изменениях архитектуры или появлении нового долгосрочного контекста._
