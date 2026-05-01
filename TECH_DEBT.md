# Технический долг — AIMA Backend

Документ описывает все шаги, необходимые для перевода backend из текущего «тестового» состояния (Railway, заглушки) в полноценный production. Создан после первого деплоя на Railway 01.05.2026.

**Текущий URL:** `https://backend-production-f2a1.up.railway.app`
**Состояние:** API живой, миграции накатаны, но реальные интеграции не подключены — стоят заглушки `changeme` / `https://example.com`.

---

## Содержание

- [🔴 Критично — без этого нет рабочего прода](#-критично)
- [🟡 Желательно — для полноценного прода](#-желательно)
- [🟢 Инфраструктура и код](#-инфраструктура-и-код)
- [Сводка переменных](#сводка-переменных)
- [История фиксов (что было сломано в репо изначально)](#история-фиксов)

---

## 🔴 Критично

### 1. Keycloak

**Сейчас:** заглушки `https://example.com`. Любая попытка логина / регистрации / refresh-токена упадёт.

**Что сделать:**
- Поднять собственный Keycloak (например, отдельным сервисом на Railway: `+ New → Docker Image → quay.io/keycloak/keycloak:latest`, либо на VPS).
- Создать realm (например `lumi`).
- Создать два клиента:
  - `web-app` (public, для приложения и админки)
  - `admin-cli` (confidential, для backend-операций над пользователями)
- Сгенерировать `CLIENT_SECRET` для каждого.
- Завести админ-пользователя для admin-cli.

**Заменить переменные:**
```
keycloak__admin__SERVER_URL          → https://your-keycloak.up.railway.app
keycloak__admin__USERNAME            → admin
keycloak__admin__PASSWORD            → (реальный)
keycloak__admin__REALM_NAME          → lumi
keycloak__open_id__SERVER_URL        → https://your-keycloak.up.railway.app
keycloak__open_id__REALM_NAME        → lumi
keycloak__open_id__CLIENT_SECRET_KEY → (реальный из Keycloak)
```

---

### 2. MinIO / S3 (хранилище файлов)

**Сейчас:** `minio__endpoint=localhost:9000` — заглушка. Загрузка файлов и выдача media-URL не работают.

**Варианты:**
- Поднять MinIO на Railway: `+ New → Docker Image → minio/minio` с `server /data --console-address :9001`. Подключить volume.
- Использовать AWS S3 / Cloudflare R2 / Backblaze B2 — `minio` SDK совместим с любым S3-API. Меняется endpoint и ключи.

**Заменить:**
```
minio__endpoint    → minio.railway.internal:9000  (или s3.amazonaws.com / R2-endpoint)
minio__access_key  → (реальный)
minio__secret_key  → (реальный)
minio__bucket      → aima-uploads  (создать руками)
```

---

### 3. Firebase Cloud Messaging (push-уведомления)

**Сейчас:** отключён через `firebase__enabled=false` (по дефолту). Push-уведомления о новых задачах не отправляются.

**Шаги:**
- Создать новый Firebase-проект на `firebase.google.com → Add project`.
- Service Account → Generate new private key → скачать JSON.
- Залить файл в Railway volume (см. п. 13).

**Включить:**
```
firebase__enabled          → true
firebase__credentials_path → /app/secrets/firebase_credentials.json
```

---

### 4. Apple Sign-In

**Сейчас:** заглушки. Авторизация через Apple падает.

**Как получить ключи:**
- developer.apple.com → Account → Keys → Create a key → Sign in with Apple → скачать `.p8`.
- Записать `Key ID`, `Team ID`, `Services ID` (это `CLIENT_ID`).

**Заменить:**
```
apple_oauth__CLIENT_ID         → com.lumi.lumiapp.signin  (Services ID)
apple_oauth__TEAM_ID           → (10-значный из Apple Dev)
apple_oauth__KEY_ID            → (10-значный)
apple_oauth__PRIVATE_KEY_FILE  → /app/secrets/apple_private_key.p8
apple_oauth__REDIRECT_URI      → https://api.aima.kz/auth/oauth/apple/callback
```

И **залить `.p8` в volume** `/app/secrets/`.

---

### 5. Google OAuth

**Где взять:** console.cloud.google.com → APIs & Services → Credentials → OAuth client ID → Web application.

**Заменить:**
```
google_oauth__CLIENT_ID      → xxxxx.apps.googleusercontent.com
google_oauth__CLIENT_SECRET  → GOCSPX-xxxxx
google_oauth__REDIRECT_URI   → https://api.aima.kz/auth/oauth/google/callback
```

В Google Console добавить этот redirect_uri в Authorized redirect URIs.

---

### 6. FreedomPay (платежи)

**Сейчас:** заглушки. Оплата подписок не работает.

**Шаги:**
- Зарегистрировать юрлицо у FreedomPay.kz, заключить договор.
- Получить `MERCHANT_ID` и `SECRET`.

**Заменить:**
```
freedom_pay__MERCHANT_ID  → (реальный)
freedom_pay__SECRET       → (реальный)
freedom_pay__CALLBACK_URL → https://api.aima.kz/payments/callback
```

В кабинете FreedomPay тоже зарегистрировать callback URL.

---

## 🟡 Желательно

### 7. Email (рассылка кодов подтверждения, паролей)

**Заменить:**
```
email_client__EMAIL       → noreply@aima.kz
email_client__PASSWORD    → app-password (для Gmail — App Password из Google Account → Security → 2-step → App passwords)
email_client__SMTP_SERVER → smtp.gmail.com
email_client__PORT        → 587
```

---

### 8. SMSC (SMS-коды)

smsc.kz/smsc.ru — зарегистрировать аккаунт, получить логин и API-key.

```
SMSC__LOGIN  → (реальный)
SMSC__KEY    → (реальный)
SMSC__SENDER → AIMA  (зарегистрировать имя отправителя)
SMSC__DEBUG  → false
```

---

### 9. Wazzup (WhatsApp-уведомления)

wazzup24.com → API key, channel id, template id.

```
WAZZUP__API_KEY     → (реальный)
WAZZUP__CHANNEL_ID  → (реальный — сейчас стоит дефолт от Романа: 137819cc-1b5a-4063-8df4-e1a4bc1c3d9c, его надо поменять)
WAZZUP__TEMPLATE_ID → (реальный)
WAZZUP__DEBUG       → false
```

---

### 10. Telegram-бот для системных алёртов

@BotFather → /newbot → токен. Завести группу/чат для админских уведомлений.

```
telegram_bot__TOKEN   → (реальный)
telegram_bot__CHAT_ID → (id админ-чата)
```

---

### 11. Cloudflare CDN (если используется)

```
cloudflare_customer_code → (из Cloudflare account)
```

---

## 🟢 Инфраструктура и код

### 12. CORS — закрыть `allowed_origins`

**Сейчас:** `allowed_origins=*` — небезопасно. На проде ограничить до известных доменов:

```
allowed_origins = https://app.aima.kz,https://admin.aima.kz,https://aima.kz
```

---

### 13. Volume для uploads и secrets

`backend → Settings → Volumes`:
- `/app/uploads` — для загруженных файлов (если не S3)
- `/app/secrets` — для `apple_private_key.p8`, `firebase_credentials.json`

Без volume эти файлы пропадут при каждом редеплое.

---

### 14. PORT — убрать ручную переменную

Сейчас стоит `PORT=8000`, но Railway сам передаёт `PORT` (рандомный). **Удалить** переменную `PORT` из Variables — Railway передаст свой, код уже это уважает (`src/main.py` читает `os.getenv("PORT")`).

---

### 15. Кастомный домен

`backend → Settings → Networking → Custom Domain` → `api.aima.kz`. Настроить CNAME у регистратора. После — переписать все callback URL с `backend-production-f2a1.up.railway.app` на `api.aima.kz`.

---

### 16. SSL

Railway сам выпускает Let's Encrypt. Делать ничего не нужно.

---

### 17. Health-check / автоперезапуск

`backend → Settings → Healthcheck path: /health` — роут уже есть. Railway будет пинговать его и автоматически рестартовать при 3+ фейлах.

---

### 18. Лимиты ресурсов

`backend → Settings → Resources`. Для прод-нагрузки минимум:
- backend: 1 vCPU / 1 GB RAM
- Postgres: 2 GB RAM

---

### 19. Бэкапы Postgres

`Postgres → Backups → Enable daily backups`. Платная фича, но критично для прода.
Альтернатива — настроить `pg_dump` через cron в свой S3.

---

### 20. Мониторинг и логи

Railway даёт встроенные **Metrics** и **Logs**. Для серьёзного прода добавить:
- **Sentry** для ошибок: `pip install sentry-sdk[fastapi]` + переменная `SENTRY_DSN`. Инициализация в `src/main.py`.
- **Grafana / Prometheus** — `prometheus_client` уже подключён, endpoint `/metrics` живой. Подключить Grafana Cloud (бесплатный тир).

---

### 21. Отключить публичный доступ к Postgres

Сейчас Postgres имеет `switchyard.proxy.rlwy.net:47781` (публичный). На проде:
`Postgres → Settings → Networking → Disable public networking`.
Backend ходит через `postgres.railway.internal`, публичный доступ опасен.

---

### 22. Sealed Variables

Все чувствительные переменные (secrets, passwords, API keys) пометить как **Sealed** — Railway зашифрует их и они не будут видны в UI после сохранения.

---

### 23. Rate limiting

В коде нет rate-limiter. На проде это критично — иначе кто угодно может задосить `/auth/code/request` и спалить SMS-баланс.

Добавить через `slowapi`:
```bash
pip install slowapi
```

И обвесить лимитами хотя бы:
- `/auth/code/request` — 1/мин на IP
- `/auth/login-swagger` — 5/мин на IP
- `/auth/registration/complete` — 3/час на IP

---

### 24. Auto-deploy и preview environments

`backend → Settings → Source → Auto-deploy from main: ON`. Можно настроить preview-окружения для веток (отдельный environment в Railway).

---

### 25. CI/CD

В репо есть `.gitlab-ci.yml` от старого окружения. На GitHub он не применяется. Нужно:
- Либо завести GitHub Actions: `lint (ruff) → safety (pip-audit) → test → deploy`.
- Либо положиться на встроенный Railway auto-deploy (минимум).

---

## Сводка переменных

| Группа | Переменных | Откуда брать |
|---|---|---|
| Keycloak | 7 | свой инстанс Keycloak |
| MinIO / S3 | 4 | Railway / AWS / R2 |
| Firebase | 1 (+ файл) | console.firebase.google.com |
| Apple OAuth | 4 (+ `.p8` файл) | developer.apple.com |
| Google OAuth | 2 | console.cloud.google.com |
| FreedomPay | 3 | freedompay.kz (договор) |
| Email | 2 | свой SMTP / Gmail App Password |
| SMSC | 3 | smsc.kz |
| Wazzup | 3 | wazzup24.com |
| Telegram | 2 | @BotFather |
| Cloudflare | 1 | cloudflare.com |

**Итого ≈ 32 секрета** для полноценного прода. Заглушки `changeme` сейчас стоят только чтобы pydantic-валидатор пропустил инициализацию.

---

## История фиксов

Эти проблемы были обнаружены и исправлены при первом деплое на Railway. Записаны как факты — не как открытые задачи.

### 1. Отсутствовал `requirements.txt`
- В репозитории не было файла зависимостей: ни `requirements.txt`, ни секции `dependencies` в `pyproject.toml` (там только конфиги ruff/vulture).
- Файл был сгенерирован вручную из импортов в `src/`.
- Также в `.gitignore` стоял паттерн `*.txt`, из-за которого новый `requirements.txt` сначала не попадал в коммит. Добавлено исключение `!requirements.txt`.

### 2. Dockerfile не собирал psycopg2
- Не были установлены `gcc` и `libpq-dev` в builder-стадии.
- Не был установлен `libpq5` в runtime-стадии.
- Добавлены apt-пакеты, прописан `PYTHONPATH=/app/src`.

### 3. PORT захардкожен в `src/main.py`
- Было: `uvicorn.run(app, host="0.0.0.0", port=8000)` — игнорирует `$PORT` от Railway.
- Стало: чтение `os.getenv("PORT", "8000")` + защита `if __name__ == "__main__"`.

### 4. Отсутствовал `email-validator`
- `KeycloakUserDTO` использует `pydantic.EmailStr`, который требует пакет `email-validator`.
- В requirements не был указан. Добавлен `pydantic[email]==2.10.3` + `email-validator==2.2.0`.

### 5. Миграция `fc858cd71edc_migration_fix.py` ломала схему
- В функции `upgrade()` строки `op.add_column(...)` для колонок `guid`, `type`, `difficulty`, `question_type` были закомментированы, но связанные `op.create_unique_constraint(...)` оставались активными.
- В результате UNIQUE-индексы пытались лечь на несуществующие колонки.
- Раскомментированы 5 add_column для таблиц: `hints`, `questions` (×2), `subjects` (×2), `topics` (×2), `variants`.

### 6. Миграция `420aa383195e_*.py` ссылалась на несуществующую колонку
- FK `trainer_attempt_answers.student_guid → students.guid` — в таблице `students` нет колонки `guid` (PK называется `id`, см. модель `src/student/models.py`).
- Заменено на `→ students.id`.

### 7. Перенос с GitLab на GitHub
- Репо изначально был у `romannvz/backend` на GitHub (с GitLab CI). Перенесён на `ppechkin574-art/backend` (`git push` со сменой remote, без переписывания истории — авторство коммитов сохранено за оригинальным автором).
- Для CI/CD на GitHub нужно либо завести GitHub Actions, либо использовать встроенный Railway auto-deploy.

---

## Дальнейшие шаги (roadmap)

**Фаза 1 — увидеть продукт (текущая стадия):**
- ✅ Backend живой на Railway
- ✅ Postgres + Redis подключены
- ✅ Миграции применены
- ⏳ Подменить URL во Flutter-приложении на Railway-домен → запустить на эмуляторе

**Фаза 2 — авторизация и базовые фичи:**
- Поднять Keycloak (см. п. 1)
- Подключить S3-хранилище (см. п. 2)
- Завести Email + SMSC (для кодов подтверждения)
- Включить Sentry

**Фаза 3 — платежи и push:**
- FreedomPay (п. 6)
- Firebase (п. 3)
- Apple Sign-In (п. 4)
- Google OAuth (п. 5)

**Фаза 4 — продакшн-готовность:**
- Кастомный домен
- Daily backups Postgres
- Rate limiting
- Закрыть CORS / публичный Postgres
- Миграция на Sealed variables

---

_Документ создан 01.05.2026. Обновлять по мере прохождения roadmap._
