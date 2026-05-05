# Технический долг — AIMA Backend

Документ описывает все шаги, необходимые для перевода backend из текущего «staging» состояния в полноценный production. Создан 01.05.2026, обновлён там же.

**Состояние стека на сейчас (04.05.2026):**
- ✅ Backend, Admin, Postgres, Redis, **Keycloak**, **MinIO** — все подняты на Railway, Active.
- ✅ Контент Романа залит из дампа: 12 предметов / 555 тем / 2821 вопрос.
- ✅ Авторизация работает (Keycloak realm `lumi`, login по номеру + Google OAuth).
- ✅ Хранилище файлов работает (MinIO, через переписанный `FileService`).
- ✅ **Email** через Resend HTTP API (домен `aima.kz` Verified).
- ✅ **SMS** через SMSC.kz (DEBUG mode, баланс 0₸).
- ✅ **Firebase Cloud Messaging** инициализирован (`aima-prod-67f9d`), backend → FCM pipeline работает.
- ✅ **Google OAuth** end-to-end (creds в Cloud Console проекте `aima-prod`).
- ✅ Романовский фич-дроп смержен (Family/Leaderboard/Users + 3 миграции).
- ⏸ **Apple Sign-In** — отложено по решению заказчика; креды есть, код готов.
- ⏸ **FreedomPay** — отложено по решению заказчика; договор подписан, код готов.
- 🟡 Wazzup (WhatsApp) и Telegram-бот alerts — заглушки `changeme`.
- 🟡 SMSC: пополнить баланс + зарегистрировать sender `AIMA` для прода.

**URL'ы:**
- Backend API: `https://backend-production-f2a1.up.railway.app/docs`
- Admin Panel: `https://admin-production-4572.up.railway.app`
- Keycloak: `https://keycloak-production-0a0c.up.railway.app`
- MinIO Console: `https://minio-production-3f82.up.railway.app`

---

## Содержание

- [Сводка внешних сервисов](#сводка-внешних-сервисов)
- [🔴 Критично — без этого нет рабочего прода](#-критично)
- [🟡 Желательно — для полноценного прода](#-желательно)
- [🟢 Инфраструктура и код](#-инфраструктура-и-код)
- [Сводка переменных](#сводка-переменных)
- [История фиксов (что было сломано в репо изначально)](#история-фиксов)

---

## Сводка внешних сервисов

| # | Сервис | Назначение | Статус | Зависит от |
|---|---|---|---|---|
| 1 | **PostgreSQL** | Главная реляционная БД (контент ЕНТ, юзеры, попытки, платежи) | ✅ Active | Railway |
| 2 | **Redis** | Кэш, WebSocket-токены, коды подтверждения | ✅ Active | Railway |
| 3 | **Keycloak** | OIDC-сервер: realms, юзеры, OAuth flows | ✅ Active | Railway + отдельный Postgres |
| 4 | **MinIO** | S3-совместимое хранилище (аватары, картинки предметов) | ✅ Active | Railway + volume |
| 5 | **Resend** | Транзакционные email через HTTP API | ✅ Active | Resend.com (3000/мес free) |
| 6 | **SMSC.kz** | SMS-коды подтверждения для KZ-номеров | ⚠️ DEBUG mode | smsc.kz (баланс 0₸) |
| 7 | **Firebase Cloud Messaging** | Push-уведомления (ежедневные тесты, новости) | ✅ Active | aima-prod-67f9d project |
| 8 | **Google OAuth** | Sign-in через Google аккаунт | ✅ Active | aima-prod-495307 Cloud project |
| 9 | **Apple Sign-In** | Sign-in через Apple ID (iOS требование App Store) | ⏸ Отложено | Apple Developer ($99/год) |
| 10 | **FreedomPay** | Приём платежей за подписку (Halyk/Forte/Jusan) | ⏸ Отложено | Юр.лицо + договор |
| 11 | Wazzup24 | WhatsApp-канал доставки кодов (альтернатива SMS) | 🟡 Stub `changeme` | wazzup24.com (опц.) |
| 12 | Telegram Bot | Канал dev-alerts + fallback доставки кодов | 🟡 Stub `changeme` | @BotFather (опц.) |

**Что значат статусы:**
- ✅ **Active** — настроено, протестировано смоук-тестом, работает в проде.
- ⚠️ **DEBUG mode** — код подключен, но сервис в тестовом режиме (для прода нужны доп.шаги).
- ⏸ **Отложено** — код готов, креды/ресурсы у заказчика есть, подключение перенесено на следующую итерацию.
- 🟡 **Stub** — заглушка `changeme` в env, никакой работы; не критично, можно жить без.

---

## 🔴 Критично

### 1. Keycloak ✅ ЗАКРЫТО (01.05.2026)

**Статус:** работает. Backend подключён к Keycloak на `https://keycloak-production-0a0c.up.railway.app`, realm `lumi` импортирован, клиенты `web-app` и `tesla-admin-panel` созданы, тестовый юзер `admin@aima.kz` логинится через `/auth/login-swagger` → возвращаются access/refresh токены.

**Остающийся минор для прод-ready:**
- Сменить пароль временного admin-юзера Keycloak (`KEYCLOAK_ADMIN_PASSWORD`) на постоянный сильный.
- ✅ Пароль `admin@aima.kz` ротирован 04.05.2026 (через Keycloak Admin API). Старый `ChangeMeAdmin123!` больше не работает. Новый — у заказчика в password manager + Railway env.
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

**Сейчас:** ✅ Подключён. Firebase Admin SDK инициализируется при старте приложения (`Firebase app initialized for project aima-prod-67f9d` в логах), credentials передаются inline через `FIREBASE__CREDENTIALS_JSON` (см. коммит `c78c7b4`). Backend → FCM pipeline работает.

**Что осталось:**
- Mobile-апп должен зарегать свой свежий FCM-токен на `POST /user/daily-tests/devices/token` после логина. Сейчас в БД 13 токенов от прошлых сессий, при тестовой рассылке через `POST /admin/notifications/test/send` все возвращают `NotRegistered` (9 авточищены). Это **frontend-задача Романа** — проверить, что Flutter после логина действительно дёргает endpoint регистрации устройства.
- Плановый push (`Daily Test Notification Scheduler`, 09:00 Asia/Almaty) идёт в холостую — нет рабочих токенов. После того, как мобила пришлёт валидный FCM-токен — надо протестировать что таски ScheduleR доходят.

**Если придётся пересоздавать Firebase project** (например, перевыпускать service account):
- `firebase.google.com → Add project` → Project name `aima-prod`
- Add app → Android (`com.lumi.lumiapp`) / iOS (`com.lumi.lumiapp`) → скачать `google-services.json` / `GoogleService-Info.plist` → положить в `app/android/app/` и `app/ios/Runner/`
- Project settings → Service accounts → Generate new private key → скачать JSON
- В Railway → service `backend` → Variables → `FIREBASE__CREDENTIALS_JSON` = base64(JSON) (строкой одной)
- Backend перезапустится сам, в логах должно появиться `Firebase app initialized for project ...`

---

### 4. Apple Sign-In

**Сейчас:** ⏸ **отложено по решению заказчика (04.05.2026)**. Креды у заказчика есть (Apple Developer аккаунт активный), но подключение перенесено на следующую итерацию — фокус сейчас на core flows + Google OAuth.

**Реальный статус кода:** клиент `src/clients/apple/client.py` готов, lazy-load приватного ключа реализован (коммит `5cce03b`). Endpoint `/auth/oauth/apple` отвечает 200 с правильным URL Apple ID. Если в Railway записать рабочие creds + положить `.p8` — заработает без изменений в коде.

**Когда возвращаться:**
- developer.apple.com → Account → Keys → Create a key → Sign in with Apple → скачать `.p8`.
- Записать `Key ID`, `Team ID`, `Services ID` (это `CLIENT_ID`).
- В Railway → backend → Variables:
```
apple_oauth__CLIENT_ID         → com.lumi.lumiapp.signin   (Services ID)
apple_oauth__TEAM_ID           → (10-значный из Apple Dev)
apple_oauth__KEY_ID            → (10-значный)
apple_oauth__PRIVATE_KEY_FILE  → /app/secrets/apple_private_key.p8
apple_oauth__REDIRECT_URI      → https://api.aima.kz/auth/oauth/apple/callback
apple_oauth__FRONTEND_REDIRECT → com.lumi.lumiapp://oauth2redirect
```
- Залить `.p8` в Railway volume `/app/secrets/` (или передать содержимое через env-переменную как сделали для Firebase в `c78c7b4`).

---

### 5. Google OAuth

**Сейчас:** ✅ **подключён и протестирован end-to-end (04.05.2026)**. Юзер залогинился через "Продолжить с Google" в эмуляторе, бэк создал юзера в Keycloak realm `lumi`, мобильный app получил access_token и открыл главный экран.

**Проект в Cloud Console:** `aima-prod` (project ID `aima-prod-495307`). Owner: `ppechkin574@gmail.com`. 3 OAuth client'а:
- Web (`aima-backend-web`) — для backend code-grant flow
- Android (`aima-android`) — package `com.lumi.lumiapp`, SHA-1 от debug keystore
- iOS (`aima-ios`) — bundle `com.lumi.lumiapp`

**Что осталось перед прод-релизом:**
- Перевести OAuth consent screen в `Production` mode (сейчас `Testing`, доступен только test users). Процедура: Google Auth Platform → Audience → `Publish app`. Если запрашиваются sensitive scopes — потребует Verification (~2-4 недели).
- Добавить в Web client SHA-1 release keystore (когда будет prod-сборка APK).

---

### 6. FreedomPay (платежи)

**Сейчас:** ⏸ **отложено по решению заказчика (04.05.2026)**. Креды у заказчика есть (договор с FreedomPay подписан, merchant_id выдан), но подключение перенесено на следующую итерацию — фокус сейчас на core flows.

**Реальный статус кода:** клиент `src/clients/freedom_pay/` готов, payment poller запускается в lifespan и опрашивает каждые 25 минут (`Found 0 pending payments` в логах). Webhook handler `/payments/callback` принимает HMAC-MD5 подписи. Если в Railway записать рабочий `MERCHANT_ID` + `SECRET` — заработает без изменений в коде.

**Когда возвращаться:**
- В Railway → backend → Variables:
```
freedom_pay__MERCHANT_ID  → (реальный merchant ID от банка)
freedom_pay__SECRET       → (реальный HMAC secret)
freedom_pay__CALLBACK_URL → https://api.aima.kz/payments/callback
```
- В кабинете FreedomPay зарегистрировать callback URL `https://api.aima.kz/payments/callback`.
- Прогнать тестовый платёж в sandbox-окружении (FreedomPay даёт тестовые карты), убедиться что callback приходит и подпись валидируется.

---

## 🟡 Желательно

### 7a. Email — заменить упоминания старого бренда в шаблонах писем

**Статус:** ✅ выполнено в коммите `755acdc` (PR #2). `Lumi → AIMA`, `lumi-unt.kz → aima.kz`, `support@lumi-unt.kz → support@aima.kz`, copyright `2025 → 2026`. Проверять при добавлении новых шаблонов.

⚠️ Не забыть **завести почтовый ящик `support@aima.kz`** на хостере (через Hoster.kz — `mail.aima.kz` MX уже настроен). Сам ящик создать в их панели управления почтой, сейчас письма от пользователей упадут в никуда.

---

### 7. Email ✅ ПОДКЛЮЧЕНО (Resend, 02.05.2026)

**Статус:** работает в production-режиме.

- **Сервис:** Resend (HTTP API), 3000 писем/мес бесплатно.
- **Регион:** Tokyo (ap-northeast-1) — изначально выбран (можно сменить на Frankfurt позже).
- **Domain:** `aima.kz` (root) — Verified. DKIM-ключ на `resend._domainkey.aima.kz`, SPF и MX для bounces на `send.aima.kz`. DNS добавлены в Hoster.kz, верификация прошла за 5 минут.
- **From:** `AIMA <noreply@aima.kz>` — письма попадают в Inbox без Spam.
- **Код переписан:** `src/clients/notification/client.py` — был `PersonalGmailClient` через `smtplib.SMTP_SSL`, стал `ResendEmailClient` через `httpx.post(api.resend.com/emails)`. Алиас сохранён для backward compat. См. коммиты `a181b41` (Resend), `b3116ac` (extra="ignore" в Settings).
- **Переменные в Railway:** `email_client__API_KEY`, `email_client__FROM_EMAIL=noreply@aima.kz`, `email_client__FROM_NAME=AIMA`. Старые SMTP-переменные удалены.

**Почему не Gmail SMTP:** Railway блокирует исходящий SMTP-трафик (порты 25/465/587). Проверено 02.05.2026: `OSError: [Errno 101] Network is unreachable` уже на этапе TCP-connect к `smtp.gmail.com`. Это политика большинства cloud-провайдеров против спама — изменить нельзя.

**Остающиеся задачи перед прод-релизом:**
- Поправить шаблон `email_verification.html` (см. п. 7a — `Lumi` → `AIMA`, `support@lumi-unt.kz` → `support@aima.kz`).
- Завести почтовый ящик `support@aima.kz` на хостере (MX `mail.aima.kz` уже настроен).
- Когда счётчик 3000/мес превысит — перейти на платный тариф Resend ($20/мес за 50k писем) или мигрировать.
- Убрать fallback с печатью кода в Deploy Logs (security: на проде не должно светиться).

---

### 7a. Шаблоны писем — заменить упоминания Lumi на AIMA

В `src/clients/notification/templates/email_verification.html` остались:
- Заголовок `Lumi` → нужно `AIMA`
- `support@lumi-unt.kz` → `support@aima.kz`
- `tesla-education.kz` → `aima.kz`

Параллельно завести почтовый ящик `support@aima.kz` на хостере (через панель Hoster.kz — MX уже настроен).

---

### 8. SMSC.kz ✅ ПОДКЛЮЧЕНО в DEBUG (02.05.2026), осталось пополнить баланс для прода

**Статус:** код связи backend ↔ SMSC работает, в DEBUG-режиме коды симулируются и пишутся в Deploy Logs. Для реальной отправки нужны 3 шага (минимум 30 минут).

**Что сделано:**
- Зарегистрирован аккаунт SMSC.kz: login `aima_app`, привязан к `ppechkin574@gmail.com`.
- Создан отдельный API-пароль (тип «API HTTP/S, SOAP, SMTP») — `b2F9b7H3a5K0x1W0`. Это безопаснее чем использовать пароль от ЛК.
- Переменные в Railway: `SMSC__LOGIN=aima_app`, `SMSC__KEY=b2F9b7H3a5K0x1W0`, `SMSC__SENDER=SMSC.KZ`, `SMSC__DEBUG=true`.
- Поправлен баг Романа в `sms_client.py`: `result["id", "N/A"]` (передавало tuple как ключ) заменено на `result.get("id", "N/A")`. См. коммит `ef5101c`.
- Тестовый запрос проходит за ~1.5 сек, код виден в Deploy Logs (`SMSC DEBUG - Simulation: ... -> Код подтверждения: NNNNNN`).

**Почему именно SMSC.kz:** изначально в коде Романа клиент `SMSCClient` ходит на `https://smsc.kz/rest/`. Подходит для KZ-рынка: прямые контракты с местными операторами, цена ~5-8 ₸/SMS (vs ~32 ₸ через Twilio), регистрация Sender ID `AIMA` за 1-3 дня (Twilio требует Brand Registration $40 + 4-6 недель), документация на русском.

**Минусы SMSC.kz:** ниже надёжность доставки (~95% vs ~99.9% у Twilio), нет WhatsApp-канала. На проде, когда выйдем за пределы KZ, стоит **рассмотреть миграцию на Twilio** — это отдельный пункт.

**Перед выходом в production надо:**

1. **Пополнить баланс SMSC** в личном кабинете (минимум 1000 ₸ ≈ 150 SMS, лучше 5000 ₸).
   - Без баланса даже DEBUG-симуляция на стороне SMSC не пройдёт (SMSC в test-режиме всё равно требует ненулевой баланс для авторизации).
   - В нашем DEBUG-режиме (через `SMSC__DEBUG=true`) backend вообще не зовёт SMSC API, поэтому работает с любым балансом — но это не для прода.

2. **Зарегистрировать имя отправителя `AIMA`** в SMSC ЛК → `Имена отправителей` → загрузить документы ИП/ТОО (свидетельство о регистрации, минимум). Модерация 1-3 рабочих дня. Без этого SMS приходят от стандартного `SMSC.KZ` или `SMS-CENTRE` — для прода непрофессионально.

3. **Снять галочку «Режим тестирования»** в SMSC → Настройки → API/SMPP. Иначе SMS уходят в виртуальную отправку без оплаты, но реально не доставляются.

4. **Переключить в Railway:**
   ```
   SMSC__DEBUG=false
   SMSC__SENDER=AIMA  (после одобрения модерации)
   ```

5. **Опционально — IP whitelist:** в SMSC → Настройки → Доступ → Адреса для доступа добавить outbound IP Railway. Усиливает безопасность (если API-пароль утечёт через утечку логов, никто не сможет использовать его с другого IP).

6. **Опционально — webhook для статусов:** в SMSC → Настройки → API/SMPP → URL для ответов и статусов прописать `https://backend-production-f2a1.up.railway.app/auth/sms/status`. Это позволит backend отслеживать доставку (доставлено / абонент недоступен / отказ оператора). Сейчас эта фича отключена.

---

### 8a. Миграция на Twilio (рассмотреть когда выйдем за пределы KZ)

SMSC покрывает только Казахстан и СНГ. Если AIMA будет работать в РФ, других странах СНГ или дальше — нужно дополнить или заменить на Twilio:
- Глобальное покрытие (200+ стран).
- 99.9%+ доставка.
- WhatsApp / Voice / MMS поддерживаются.
- Дороже (~$0.07/SMS = ~32 ₸).
- Требует Brand Registration в США (~$40 + 4-6 недель модерации).

Реализация: новый `TwilioSMSClient` параллельно с `SMSCClient`, абстракция `SMSClientInterface`, выбор провайдера через `SMS_PROVIDER=smsc|twilio` в env.

---

<!-- Legacy section moved into п.8 above -->
<details>
<summary>Изначальный краткий план SMSC (до интеграции)</summary>

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

### M1. Sentry — error monitoring (отложено, код готов)

**Сейчас:** ⏸ Код подключён в проде (PR #14, файл `src/api/__init__.py:_init_sentry`), но `SENTRY_DSN` env не задан — backend стартует с `[sentry] SENTRY_DSN not set — skipping Sentry init`. Это no-op, безопасно.

**Зачем включить (когда выйдем в Play/App Store):**
- Все 500-ошибки автоматически уходят в Sentry с полным stack trace, request body, browser/device info, user context.
- Группировка похожих exceptions, alerts в Slack/email.
- Performance monitoring (slow endpoints, p95 latency).
- Release tracking — видно в каком commit'е появилась новая ошибка.

**Free tier:** 5000 events/мес, 10к performance transactions/мес, 1 пользователь. Хватит на ~200-500 активных юзеров.

**Как включить (5 минут):**

1. **Регистрация:** https://sentry.io/signup/ → email `info@sab.com.kz` → создать аккаунт → подтвердить email.
2. **Создать проект:** Platform = Python/FastAPI, name = `aima-backend`. Не подключать SDK через onboarding (он уже в коде).
3. **Скопировать DSN** на странице "Get started" — вид `https://<key>@o<orgid>.ingest.us.sentry.io/<projectid>`.
4. **Railway:** service `backend` → Variables → Raw editor → добавить:
   ```
   SENTRY_DSN="<paste DSN>"
   SENTRY_TRACES_SAMPLE_RATE="0.05"
   ```
   (5% трасс достаточно для performance picture без перегруза free tier'а)
5. Update Variables → Railway передеплоит → в Deploy Logs появится `[sentry] initialised — env=production release=<sha>`.
6. **Проверка:** триггернуть искусственный 500 (например, SQL injection попытка) → событие должно появиться в Sentry → Issues в течение 30 секунд.

**Опциональные настройки в Sentry UI после первой пары событий:**
- Alerts → создать правило "High error count" (alert когда >10 событий/час).
- Settings → Integrations → Slack/Discord webhook (если есть рабочий канал).
- Settings → Sampling → если 5000 events/мес кончаются — поднять `SENTRY_TRACES_SAMPLE_RATE` до 0.01.

---

### 11a. SubjectServiceDTO.image — fallback на FileService.get_subject_image_url

**Найдено в аудите 04.05.2026:** `src/quiz/converters.py:to_subject_service` возвращал hardcoded `http://localhost:8000/uploads{path}` (плюс два debug `print()`). Очевидно никем не работал в проде — мобила на Pixel_7 не достучится до `localhost`.

**Минимальный фикс уже сделан** (этот коммит): `image=subject.image or ""`. Теперь возвращается raw поле из БД (либо абсолютный URL, либо относительный путь).

**Полный fix (TODO):** обернуть в каждом вызывающем сервисе через `self._file_service.get_subject_image_url(subject.image)` (как уже сделано в `subjects.py:499` для AdminSubjectDTO). Места применения: `src/quiz/services/subjects.py:195, 215, 240, 302, 333, 349, 367, 388`. Альтернатива: модифицировать `to_subject_service(subject, file_service)` — принимать file_service как параметр, и обновить все 8 вызовов.

**Симптом без фикса:** в мобиле на user-facing экранах вместо иконок предметов будут broken image placeholders (т.к. URL вроде `/images/subjects/physics.png` без domain prefix невалиден для Flutter).

---

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

### ✅ Фаза 2 — Smoke мобильного приложения (закрыто 02.05.2026)

- ✅ `Constants.baseUrl` подменён на `https://backend-production-f2a1.up.railway.app` (коммит `a3c5583` в `ppechkin574-art/app`).
- ✅ Android-эмулятор Pixel 7 + Flutter `flutter run -d emulator-5554` собрался (потребовалось почистить `.gradle/caches`, переустановить NDK).
- ✅ Приложение открылось, экран «Добро пожаловать!», login по номеру `+77001234567` / `Test12345!` (тестовый юзер в Keycloak realm `lumi`) → главный экран с реальными предметами Романа.
- ✅ Связка Flutter → Backend → Postgres → Keycloak работает.
- ✅ Попутно поправлен медленный `/user/subjects` (FileService для абсолютных URL не зовёт MinIO presigned, см. коммит `af8d09a`).

### ✅ Фаза 3 (часть) — Email + SMS подключены (02.05.2026)

- ✅ **Resend** для email — отправка с `noreply@aima.kz`, домен Verified, см. п. 7.
- ✅ **SMSC.kz** для SMS — DEBUG-режим работает, перед прод-релизом нужно пополнить баланс и зарегистрировать `AIMA` sender, см. п. 8.

### ⏳ Фаза 3 (продолжение) — Остальные внешние интеграции

В порядке приоритета:

- ⏳ **Firebase** (п. 3) — push-уведомления (ежедневные тесты, новости).
- ⏳ **Google OAuth** (п. 5) — социальный логин для студентов через Flutter.
- ⏳ **Apple Sign-In** (п. 4) — обязателен для App Store при наличии других login-методов.
- ⏳ **FreedomPay** (п. 6) — оплата подписок (требует юрлицо + договор, 1-2 недели).
- ⏳ **Telegram-бот для алёртов** (п. 10) — уведомления админам о падениях.
- ⏳ **Wazzup** (п. 9) — WhatsApp-уведомления (опционально, как fallback к SMS).

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
