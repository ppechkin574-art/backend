# Технический долг — AIMA Backend

Документ описывает все шаги, необходимые для перевода backend из текущего «staging» состояния в полноценный production. Создан 01.05.2026, обновлён там же.

**Состояние стека на сейчас:**
- ✅ Backend, Admin, Postgres, Redis, **Keycloak**, **MinIO** — все подняты на Railway, Active.
- ✅ Контент Романа залит из дампа: 12 предметов / 555 тем / 2821 вопрос.
- ✅ Авторизация работает (Keycloak realm `lumi`).
- ✅ Хранилище файлов работает (MinIO, через переписанный `FileService`).
- ❌ Внешние интеграции: Firebase, Apple/Google OAuth, FreedomPay, SMTP/SMS/WhatsApp/Telegram — стоят заглушки. Без них приложение не сможет:
  - регистрировать пользователей через email/SMS-коды,
  - принимать оплату подписок,
  - отправлять push,
  - логиниться через Apple/Google.

**URL'ы:**
- Backend API: `https://backend-production-f2a1.up.railway.app/docs`
- Admin Panel: `https://admin-production-4572.up.railway.app`
- Keycloak: `https://keycloak-production-0a0c.up.railway.app`
- MinIO Console: `https://minio-production-3f82.up.railway.app`

---

## Содержание

- [🔴 Критично — без этого нет рабочего прода](#-критично)
- [🟡 Желательно — для полноценного прода](#-желательно)
- [🟢 Инфраструктура и код](#-инфраструктура-и-код)
- [Сводка переменных](#сводка-переменных)
- [История фиксов (что было сломано в репо изначально)](#история-фиксов)

---

## 🔴 Критично

### 1. Keycloak ✅ ЗАКРЫТО (01.05.2026)

**Статус:** работает. Backend подключён к Keycloak на `https://keycloak-production-0a0c.up.railway.app`, realm `lumi` импортирован, клиенты `web-app` и `tesla-admin-panel` созданы, тестовый юзер `admin@aima.kz` логинится через `/auth/login-swagger` → возвращаются access/refresh токены.

**Остающийся минор для прод-ready:**
- Сменить пароль временного admin-юзера Keycloak (`KEYCLOAK_ADMIN_PASSWORD`) на постоянный сильный.
- Сменить пароль `admin@aima.kz` (был temporary `ChangeMeAdmin123!`).
- Включить email-verification в realm `lumi → Realm settings → Login`, заполнить SMTP в `Realm settings → Email`.
- Защитить `master` realm — отключить self-registration на нём (по умолчанию отключено, проверить).

<details>
<summary>Изначальные заметки (что было до фикса)</summary>

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

</details>

---

### 2. MinIO / S3 (хранилище файлов) ✅ ЗАКРЫТО (01.05.2026)

**Статус:** работает. MinIO развёрнут на Railway с volume `/data`, bucket `aima-uploads` создан, отдельный service account с restricted policy. Backend подключён через приватную сеть `minio.railway.internal:9000`.

**Дополнительно:** оригинальный `FileService` Романа сохранял файлы на **локальный диск** контейнера через `open(file, "wb")` — на эфемерных контейнерах Railway это не работает. Переписан на `MediaStorageClientMinio.save()/link()/remove()`. Все аватары и subject-images теперь идут в S3-bucket. См. коммит `ecca173`.

**Остающиеся задачи перед прод-ready:**
- Залить subject_images/* (10 файлов из `lumipack/subject_images/`) в bucket `aima-uploads/subjects/` через `mc.exe`.
- Настроить регулярные бэкапы bucket (Railway не делает их автоматически для MinIO; либо переключиться на Cloudflare R2 / AWS S3, что уже не критично — код S3-агностичен).
- Сменить дефолтный пароль `aima_admin / Aima2026MinioStrongPassXyz` на настоящий сильный.

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

### 7a. Email — заменить упоминания старого бренда в шаблонах писем

**Сейчас в `src/clients/notification/templates/email_verification.html`:**
- Заголовок: **«Lumi»** / **«Lumi App»**
- Subject: **«Код подтверждения AIMA»** (это уже актуально, но шапка в письме всё ещё Lumi)
- Support email: **`support@lumi-unt.kz`** (это домен Романа, нерабочий для нас)
- Сайт: **`tesla-education.kz`** (тоже Романа)

**Что заменить:**
- Все упоминания `Lumi` → `AIMA`
- `support@lumi-unt.kz` → `support@aima.kz`
- `tesla-education.kz` → `aima.kz`

⚠️ Параллельно нужно **завести почтовый ящик `support@aima.kz`** на хостере (через Hoster.kz — у пользователя `mail.aima.kz` MX уже настроен на хостер). Сам ящик создать в их панели управления почтой.

Проверять при правке: `email_verification.html` — основной файл. Если будут добавлены другие шаблоны (`password_reset.html`, `subscription_expired.html` и т.д.) — пройти по всем.

---

### 7. Email — переписать с SMTP на HTTP API сервис

⚠️ **Railway блокирует исходящий SMTP-трафик** (порты 25/465/587). Проверено 02.05.2026 с Gmail App Password — `OSError: [Errno 101] Network is unreachable` уже на этапе TCP-connect к `smtp.gmail.com`. Это политика большинства cloud-провайдеров против спама — изменить нельзя.

**Что нужно сделать:**

1. **Завести аккаунт в HTTP-email-сервисе.** Бесплатные варианты по убыванию лимита:
   - **Resend** — 3000 писем/мес, https://resend.com
   - **Brevo (бывший Sendinblue)** — 300 писем/день, https://brevo.com
   - **SendGrid** — 100 писем/день, https://sendgrid.com
   - **Postmark** — 100 писем/мес trial
   - **Mailgun** — 100 писем/день в sandbox

2. **Получить API key.**

3. **Переписать `src/clients/notification/client.py.NotificationClientEmail`** с `smtplib` на HTTP-вызов через `httpx`/`requests`. Например для Resend:
   ```python
   httpx.post("https://api.resend.com/emails",
              headers={"Authorization": f"Bearer {api_key}"},
              json={"from": from_addr, "to": [to_addr], "subject": subject, "html": body})
   ```

4. **Заменить переменные:**
   ```
   email_client__API_KEY     → re_xxxxxxx (Resend) или аналог
   email_client__FROM_EMAIL  → noreply@aima.kz
   email_client__PROVIDER    → resend (или brevo/sendgrid)
   ```

5. **Удалить** `email_client__SMTP_SERVER`, `email_client__PORT`, `email_client__PASSWORD` — больше не нужны.

**Текущий fallback:** при провале отправки backend пишет в Deploy Logs `КОД ДЛЯ РАЗРАБОТКИ: NNNNNN`. Это позволяет тестировать регистрацию читая код из логов, но **в production этот fallback нужно убрать** (security: не светить код в логах).

<details>
<summary>Изначальный план (не работает на Railway)</summary>

```
email_client__EMAIL       → noreply@aima.kz
email_client__PASSWORD    → app-password (для Gmail — App Password из Google Account → Security → 2-step → App passwords)
email_client__SMTP_SERVER → smtp.gmail.com
email_client__PORT        → 587
```

При попытке отправить через Gmail App Password (`oxybcecrgnrjnfga`) backend получил `Network is unreachable` — Railway не пропускает SMTP-пакеты наружу. Любой SMTP-сервис будет давать тот же эффект.

</details>

---

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

### 26. Полное покрытие тестами (юнит + интеграционные)

**Почему важно:** в проекте сейчас **нет ни одного теста**. Каждый новый релиз = риск 500-ошибок и регрессий, которые ловятся только в проде. Совет от изначального автора (`romannvz`): «крайне необходимы тесты, хотя бы юнит, в идеале — интеграционные».

**План:**
- **Юнит-тесты:** `pytest` для сервисов (`AuthService`, `QuestionService`, `PaymentService`, `SubscriptionService`). Моки UoW и внешних клиентов.
- **Интеграционные:** `pytest` + `testcontainers` (Postgres + Redis в Docker для каждой сессии). Прогон критичных флоу:
  - регистрация → подтверждение кода → логин → refresh token
  - создание платежа → callback → активация подписки
  - попытка теста → проверка ответов → расчёт результата
- **CI:** `GitHub Actions` запускает тесты на каждый PR.
- **Coverage target:** 60% на старте, 80% к выходу в прод.

Объём работы — недели, но это единственный способ предотвратить «каждый релиз 500 или баг».

---

### 27. Подключить Pylance / strict typing

**Почему важно:** совет от `romannvz`: «процентов 80 проблем отсеется само собой красным подчёркиванием ещё на этапе пуша в гит».

**План:**
- Добавить `.vscode/settings.json` в репо с `python.analysis.typeCheckingMode: strict` (или хотя бы `basic`).
- Добавить `mypy` в `requirements-dev.txt`, прогнать на проекте, проставить `# type: ignore` где невозможно исправить за разумное время.
- В CI добавить шаг `mypy src/` (после ruff).
- Договориться с командой что красные подчёркивания в IDE — **блокер**, нельзя коммитить с ошибками типов.

Эффект: на этапе разработки увидим 80% проблем (DTO, маппинг полей, `None`-handling) до того как они попадут в прод.

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

Эти проблемы были обнаружены и исправлены при первом деплое на Railway. Записаны как факты — не как открытые задачи. Полный список см. в [CLAUDE.md → "Что было сломано"](./CLAUDE.md#что-было-сломано-в-исходном-репо-важно-при-отладке).

Краткая сводка:
1. **Сборка:** не было `requirements.txt`, в Dockerfile не было `gcc/libpq-dev/libpq5`, `main.py` хардкодил порт 8000.
2. **Зависимости:** не было `email-validator` (хотя `KeycloakUserDTO` использует `EmailStr`).
3. **Миграции:** `fc858cd71edc` создавала UNIQUE на закомментированных колонках; `420aa383195e` ссылалась на `students.guid` вместо `students.id`; наша миграция `d1f2a8c4e5a0` дублировала колонку из дампа.
4. **DTO:** `KeycloakUserDTO.createdTimestamp/emailVerified/enabled` и `UserDTO.created_at/updated_at` были обязательными, но Keycloak/БД для realm-imported юзеров их не возвращали. Сделаны опциональными.
5. **Apple OAuth клиент** синхронно читал `.p8` файл при init → краш если файла нет. Сделан ленивым.
6. **CORSMiddleware** добавлялся первым (становился самым внутренним) → preflight OPTIONS падал 400. Перемещён в outermost + поддержка `allow_origin_regex` для wildcard.
7. **FileService** сохранял на локальный диск контейнера → файлы пропадали на Railway. Переписан на MinIO через существующий `MediaStorageClientMinio`.
8. **Redis-кеш** с TTL 7 дней содержал stale `data:[]` после массового изменения БД → questions/topics возвращали пусто. Добавлен `/admin/cache/flush` endpoint.
9. **Перенос с GitLab на GitHub:** репо изначально был у `romannvz/backend` (с GitLab CI). Перенесён на `ppechkin574-art/backend` через `git push` со сменой remote, без переписывания истории.

---

## Дальнейшие шаги (roadmap)

### ✅ Фаза 1 — Staging (закрыто 01.05.2026)

- ✅ Backend живой на Railway (`backend-production-f2a1.up.railway.app`)
- ✅ Postgres + Redis подключены
- ✅ Миграции применены, все ~35 миграций накатаны
- ✅ Контент Романа залит из дампа (12 предметов / 555 тем / 2821 вопрос)
- ✅ Keycloak поднят, realm `lumi` импортирован, авторизация работает
- ✅ MinIO поднят, bucket `aima-uploads` создан, FileService переписан на S3
- ✅ Admin-панель развёрнута, видит весь контент
- ✅ CORS, кеш-инвалидация, валидация Keycloak — всё починено

### ⏳ Фаза 2 — Запуск мобильного приложения (следующий шаг)

- ⏳ Подменить `Constants.baseUrl` во Flutter-приложении (`ppechkin574-art/app`) на `https://backend-production-f2a1.up.railway.app`.
- ⏳ Запустить Pixel 7 эмулятор → `flutter run -d emulator-5554`.
- ⏳ Проверить что приложение открывается, видит контент.
- ⚠️ **Без SMS-провайдера** регистрация по номеру не пройдёт. Логин email/password может работать через Keycloak — проверить.

### ⏳ Фаза 3 — Внешние интеграции для прод-фич

В этом порядке (зависит от срочности):

- ⏳ **Email + SMSC** (пп. 7-8) — нужны для регистрации/восстановления пароля.
- ⏳ **Firebase** (п. 3) — push-уведомления о ежедневных тестах.
- ⏳ **Google OAuth** (п. 5) — социальный логин для студентов.
- ⏳ **Apple Sign-In** (п. 4) — обязателен для App Store при наличии других login-методов.
- ⏳ **FreedomPay** (п. 6) — оплата подписок (требует юрлицо + договор).
- ⏳ **Telegram-бот** (п. 10) — желателен для production-алертов backend.
- ⏳ **Wazzup** (п. 9) — WhatsApp-уведомления (опционально).

### ⏳ Фаза 4 — Прод-готовность инфраструктуры

- ⏳ Кастомные домены (`api.aima.kz`, `admin.aima.kz`, `auth.aima.kz`).
- ⏳ Закрыть public networking у Postgres (п. 21).
- ⏳ Включить Postgres backups (п. 19).
- ⏳ Sealed Variables для секретов (п. 22).
- ⏳ Sentry + Grafana мониторинг (п. 20).
- ⏳ Rate limiting через slowapi (п. 23).
- ⏳ GitHub Actions CI (п. 25).
- ⏳ Сменить все тестовые пароли (Keycloak admin, MinIO root, app admin).
- ⏳ Email verification в Keycloak realm.

### ⏳ Фаза 5 — Содержательное наполнение

- ⏳ Залить subject_images/ (10 файлов из `lumipack/subject_images/`) в MinIO bucket `aima-uploads/subjects/`.
- ⏳ Создать собственный Firebase-проект для AIMA (новый `lumi-XXXXX`).
- ⏳ Настроить Apple Developer аккаунт + Service ID.
- ⏳ Настроить Google Cloud OAuth Consent Screen + clients.

---

<details>
<summary>Архив: первоначальный план (что планировалось до того как сделали)</summary>

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

</details>

---

_Документ создан 01.05.2026. Последнее обновление — 01.05.2026 (после деплоя всех инфраструктурных сервисов и наката контента)._
