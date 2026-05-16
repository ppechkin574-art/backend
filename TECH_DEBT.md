# Технический долг — AIMA Backend

Документ описывает все шаги, необходимые для перевода backend из текущего «staging» состояния в полноценный production. Создан 01.05.2026, обновлён там же.

**Состояние стека на сейчас (04.05.2026):**
- ✅ Backend, Admin, Postgres, Redis, **Keycloak**, **MinIO** — все подняты на Railway, Active.
- ✅ Контент Романа залит из дампа: 12 предметов / 555 тем / 2821 вопрос.
- ✅ Авторизация работает (Keycloak realm `lumi`, login по номеру + Google OAuth).
- ✅ Хранилище файлов работает (MinIO, через переписанный `FileService`).
- ✅ **Email** через Resend HTTP API (домен `aima.kz` Verified).
- ✅ **SMS** через SMSC.kz (07.05.2026 — реальные SMS, баланс ~1010 ₸, `SMSC__DEBUG=false`).
- ✅ **Firebase Cloud Messaging** инициализирован (`aima-prod-67f9d`), backend → FCM pipeline работает.
- ✅ **Google OAuth** end-to-end (creds в Cloud Console проекте `aima-prod`).
- ✅ Романовский фич-дроп смержен (Family/Leaderboard/Users + 3 миграции).
- ⏸ **Apple Sign-In** — отложено по решению заказчика; креды есть, код готов.
- ⏸ **FreedomPay** — отложено по решению заказчика; договор подписан, код готов.
- 🟡 Wazzup (WhatsApp) и Telegram-бот alerts — заглушки `changeme`.
- 🟡 SMSC: остался опциональный sender `AIMA` (модерация 1-3 дня, нужны документы ИП/ТОО). Сейчас SMS приходят от стандартного `SMSC.KZ`.

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
| 6 | **SMSC.kz** | SMS-коды подтверждения для KZ-номеров | ✅ Active | smsc.kz (баланс ~1010 ₸, sender `SMSC.KZ`) |
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
- ✅ Пароль `admin@aima.kz` ротирован 04.05.2026 (через Keycloak Admin API). Старый `ChangeMeAdmin123!` больше не работает.
- ✅ Пароль `admin@aima.kz` повторно ротирован 07.05.2026 (заказчик потерял предыдущий). Сгенерирован 20-символьный alphanumeric, проверен на token grant против realm `lumi` — выдаётся access_token. Хранится у заказчика в password manager.
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

### 6. FreedomPay (платежи) — ✅ ЗАКРЫТО (07.05.2026 21:33)

**TL;DR:** платёж 4990 KZT прошёл E2E, payment_id `1761666995`, webhook `/fp/result_notify` дошёл, Keycloak обновлён в PRO. Клиент после re-login видит «PRO подписка / Активна ещё 29 дней». Решение: пять одновременных правок в `init_payment` параметрах (см. коммит `7612d35`).

**Что сработало (вероятно `pg_user_country=KZ` сделал основной импульс):**
1. Добавлен `pg_user_country=KZ` — vue-tel-input на customer-странице больше не дефолтит на RU валидацию (`+7` коллидирует между KZ и RU)
2. Реальный IP юзера из `request.client.host` вместо хардкода `127.0.0.1` — вышли из anti-fraud strict mode
3. Удалён мёртвый `pg_skip_user_form=1` — параметр игнорировался FreedomPay'ем, только мутил подпись
4. Добавлен `pg_currency=KZT` — явно вместо дефолта мерчанта
5. `pg_testing_mode` вынесен в env (`FREEDOM_PAY__TESTING_MODE`, default `1`) — когда менеджер переведёт магазин в боевой режим, поставим `0` без релиза кода

**Двойной `iti-flag kz` в их форме всё ещё виден в логах** (`preferred items count: 2`) — это их внутренний баг vue-tel-input, не зависит от наших параметров, но больше не блокирует submit раз форма теперь принимает наш ввод.

**Что сделать когда мерчант перейдёт в прод:**
- Railway env: `FREEDOM_PAY__TESTING_MODE=0`
- Тестовая карта `4111 1111 1111 1111` перестанет работать, использовать реальные KZ-карты Halyk/Forte/Jusan
- Опционально — ротировать `freedom_pay__SECRET` (старый засветился в TECH_DEBT/коммитах)

**Малый UX-долг:**
- После успешной оплаты приложение **не рефрешит access_token** автоматически. Юзер видит «Пробный TRIAL» в Профиле пока не выйдет-зайдёт. Решение: после WebSocket события `payment_success` клиент должен вызвать `/auth/refresh` через refresh_token, либо ProfileInfoCubit должен делать `getUser()` при возврате с PaymentWebViewScreen (сейчас делает `context.go(AppRoutes.profile)` который пересоздаёт cubit, но cached токен — старый).
- Файл: `lib/features/profile/presentation/screens/subscription_profile_screen.dart:124-137` (`_handlePaymentState` после `PaymentResult.success`).

---

#### Историческая справка — что было до фикса

**Бэкенд работал идеально** (FreedomPay принимал запросы, redirect_url возвращался, WebSocket подключался). **Платёж застревал на customer-форме** (`https://customer.freedompay.kz/pay.html`): после нажатия «Оплатить» поле телефона помечалось красным с ошибкой «Введите ваш номер телефона», сабмит не происходил. Воспроизводилось на iOS Simulator И на реальном iPhone (TestFlight 1.2.0+11).

#### Текущий конфиг (Railway env, бэкенд)
```
freedom_pay__MERCHANT_ID   = 584797
freedom_pay__SECRET        = tawJQQsOHV03wwnn   (Секретный ключ для приёма)
freedom_pay__API_URL       = https://api.freedompay.kz
freedom_pay__PAYMENT_PAGE  = https://api.freedompay.kz/init_payment.php
freedom_pay__CALLBACK_URL  = https://backend-production-f2a1.up.railway.app
```
Магазин в FreedomPay: ТОО «SARY ARQA BELT», статус **Тестовый**. Менеджер `+7 777 802 0018`. В кабинете магазина (`my.freedompay.kz` → Магазины → #584797) поля `CHECK URL`, `RESULT URL`, `SUCCESS URL` **пустые** — мы передаём их в каждом запросе через `pg_*_url` параметры, так что это не блокер. Тестовые карты (доступны в кабинете «Разработчикам»): `4111 1111 1111 1111`, `4444 4444 4444 6666`, `5555 5555 5555 5557` и др. (CVC `123`, expire `12/26`).

#### Что точно работает (подтверждено логами Railway)
- `POST /user/subscription/create-payment` → 201 Created
- Запрос в FreedomPay `init_payment` → 200 OK с `pg_status=ok` и валидным `pg_redirect_url`
- DB-запись Payment создаётся, `pg_payment_id` пишется
- WebSocket-токен генерируется, клиент подключается, heartbeats летают
- На фронте `PaymentWebViewScreen` загружает `https://customer.freedompay.kz/pay.html?customer=<UUID>`, страница рендерится

#### В чём именно блокер
FreedomPay's customer page — Vue.js приложение, для номера телефона использует библиотеку `vue-tel-input`. После нажатия «Оплатить»:
- Через JS-инъекцию в WebView (см. `payment_webview_screen.dart::_injectDebugScript`) видно: `Forms count: 0` (не классическая HTML-форма, а Vue-приложение).
- В DOM вешаются классы ошибок `tel__wr--error`, `tel__label--error :: Введите ваш номер телефона` независимо от формата ввода.
- В preferred-странах **два элемента с `iti-flag kz`** (оба Казахстан, странно), `data-country-code` отсутствует, в `<span class="dropdown__text">` обрезается при дампе.
- Программный `click()` по preferred-элементам не помогает (Vue реактивность игнорирует DOM-клик без user-gesture).
- `__vue__` и `__vueParentComponent` хуки на `.vue-tel-input` элементе пустые → доступ к Vue-инстансу заблокирован.

Форматы которые пробовали (все отвергаются):
- `+77031234567`
- `77031234567`
- `7031234567`
- `+7 (703) 123-45-67`
- Pre-filled через `pg_user_phone` (форма показывает корректный `+7 703 123 4567`, но валидация всё равно падает).

#### Что мы сделали сегодня (07.05.2026)
**Backend (`src/payments/services.py`)**, итерации в коммитах `407a9b9` → `c8be996` → `8e76090` → `3d6c102` → `9a042da` → `04b21b8` → `1261b22`:
1. Стрипали `+` из телефона → не помогло
2. Полностью убирали `pg_user_phone` и `pg_user_contact_email` → форма требует ручного ввода и ругается
3. Возвращали оба параметра, фильтруя `None` и `'None'` строки → форма красит phone красным
4. Фильтруем синтетические email с доменом `.internal` (Keycloak их генерит для phone-only регистрации) → email-поле перестало ругаться, проблема локализована к телефону
5. **Финальный текущий стейт (`1261b22`):** шлём `pg_user_phone` (только цифры), `pg_user_contact_email` (real только), `pg_user_ip=127.0.0.1`, `pg_skip_user_form=1`. Параметр `pg_skip_user_form` похоже игнорируется FreedomPay'ем — форма показывается всё равно.

**Frontend (`lib/features/promocode/presentation/screens/payment_webview_screen.dart`)**:
- Чинили баг `clearPaymentEntity()` который не очищал `paymentEntity` из-за бага в `copyWith` — это вызывало двойной push WebView (см. `subscription_state.dart` и `subscription_cubit.dart`)
- Возвращали Android User-Agent в WebView (был временно убран)
- Добавили `JavaScriptChannel('FlutterDebug')` + injection-скрипт для перехвата `console.log`, `window.error`, кликов, ошибок валидации
- Скрипт пытается автоматически кликнуть Казахстан в дропдауне — без эффекта

**Версии собранных билдов:**
- TestFlight `1.2.0+10` — со старыми багами `clearPaymentEntity`
- TestFlight `1.2.0+11` — все фиксы + JS-инъекция (тестировался юзером 07.05.2026 на реальном iPhone — та же проблема)

#### Что попробовать завтра
1. **Связаться с менеджером FreedomPay** (`+7 777 802 0018`) — текст готов в чате, отправить в Telegram/Whatsapp.
2. **Тестовые карты конкретно от FreedomPay** (не стандартные Visa) — попробовать `4444 4444 4444 6666` вместо `4111 1111 1111 1111`. Возможно тестовый мерчант принимает только их собственные.
3. **Перевести магазин в боевой режим** (через менеджера) — в проде форма часто работает иначе. Договор уже подписан, статус «Тестовый» в кабинете нужно сменить.
4. **Альтернатива — Apple Pay через FreedomPay** — у них есть SDK для нативного ApplePayButton, обходит customer-форму вообще. См. `https://docs.freedompay.kz/`.
5. **Альтернатива 2** — JS-widget вместо redirect URL. FreedomPay даёт виджет (`pg_form_skin`?), может встраивается лучше в WebView.
6. **Webhook test** — независимо от UI, проверить что callback на `/fp/result_notify` реально приходит когда платёж оплачивается через тестовую карту в браузере (не через WebView).

#### Файлы где трогали
- Backend: `src/payments/services.py:75-99` (params построение)
- Frontend: `lib/features/subscription/presentation/cubit/subscription_state.dart` (фикс `copyWith`)
- Frontend: `lib/features/subscription/presentation/cubit/subscription_cubit.dart` (`clearPaymentEntity`)
- Frontend: `lib/features/profile/presentation/screens/subscription_profile_screen.dart` (показ ошибок payment в UI)
- Frontend: `lib/features/promocode/presentation/screens/payment_webview_screen.dart:59-200` (User-Agent + JS-инъекция)

#### Что НЕ нужно делать
- Не трогать `pg_skip_user_form` — параметр кажется не поддерживается, но и вреда не наносит
- Не убирать `pg_user_phone`/`pg_user_contact_email` снова — без них форма требует ручной ввод и юзеру это совсем не дружелюбно
- Не амендить старые коммиты — оставить аудит-трейл всех попыток

---

## 🟡 Желательно

### 7a. Email — заменить упоминания старого бренда в шаблонах писем

**Статус:** ✅ выполнено в коммите `755acdc` (PR #2). `Lumi → AIMA`, `lumi-unt.kz → aima.kz`, copyright `2025 → 2026`. Поддержка-контакт обновлён до `info@sab.com.kz` (рабочая корп.почта заказчика, PR от 04.05.2026). Проверять при добавлении новых шаблонов.

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
- ✅ Поправить шаблон `email_verification.html`: `Lumi` → `AIMA`, support-email → `info@sab.com.kz` (рабочая корп.почта SAB).
- _(не нужно)_ заводить отдельный mailbox на хостере — `info@sab.com.kz` уже существует у заказчика.
- Когда счётчик 3000/мес превысит — перейти на платный тариф Resend ($20/мес за 50k писем) или мигрировать.
- Убрать fallback с печатью кода в Deploy Logs (security: на проде не должно светиться).

---

### 7a. Шаблоны писем — заменить упоминания Lumi на AIMA

В `src/clients/notification/templates/email_verification.html` остались:
- Заголовок `Lumi` → нужно `AIMA`
- `support@lumi-unt.kz` → `info@sab.com.kz`
- `tesla-education.kz` → `aima.kz`

_(не требуется заводить отдельный mailbox — `info@sab.com.kz` уже работает у заказчика SAB.)_

---

### 8. SMSC.kz ✅ ПОЛНОСТЬЮ В ПРОДЕ (07.05.2026)

**Статус:** боевые SMS реально доставляются. Подтверждено end-to-end: 3 теста с `+77787943760`, ~51 ₸ списано, баланс ~1010 ₸.

**Что добавлено сегодня:**
- Баланс пополнен через PayBox (опция 4 в кассе SMSC), 970 ₸ + 93.75 ₸ верификационный бонус.
- `SMSC__DEBUG=false` в Railway (через `railway variables --set`).
- Frontend (`register_user_remote_source.dart`, `reset_password_remote_source.dart`) переключен с `platform: "whatsapp"` на `"sms"` — Wazzup был в DEBUG и тихо «глотал» все коды; см. секцию 9 ниже про возврат WA.
- **Найден и починен баг в `sms_client.py`**: код использовал `apikey=`, но `SMSC__KEY` хранит дополнительный API-пароль (тип «API HTTP/S»), а не токен. SMSC возвращал error 2 «authorise error». Заменено на `login=+psw=`. Коммит `9f374b4`.
- Метки error-кодов поправлены: `2` теперь «authorise error», `3` — «insufficient balance» (раньше были перепутаны и сбивали с толку при дебаге).

**Хардендинг безопасности (07.05.2026, аудит после активации):**
- `block:contact:<phone>` теперь реально SETEX'ится на 60 секунд после успешной отправки (per-phone rate limit). Ранее ключ только проверялся, не ставился — был no-op. Защищает от спама с IP-ферм против одного номера.
- `_send_code_to_dev_channel` больше не пишет код подтверждения и полный контакт в Telegram dev-чат. Контакт маскируется через `_mask_contact` (`+7778***3760`, `us***@aima.kz`).
- Лог `КОД ДЛЯ РАЗРАБОТКИ: %s (для %s)` (services.py:888 и :909) удалён — раньше код подтверждения попадал в Railway/Sentry stdout в открытом виде.
- `_send_confirmation_code` теперь возвращает `bool` (success); rate-limit ставится только при успехе primary-канала, чтобы не банить юзера если SMSC сам упал. Коммит `a39aa5e`.

**Что всё ещё опционально:**

1. **Зарегистрировать sender `AIMA`** в SMSC ЛК → `Имена отправителей` → загрузить документы ИП/ТОО. Модерация 1-3 рабочих дня. Сейчас SMS приходят от `SMSC.KZ` — функционально ОК, но непрофессионально. Когда одобрят — Railway: `SMSC__SENDER=AIMA`.
2. **IP whitelist** в SMSC → Настройки → Доступ. Усилит защиту если API-пароль утечёт.
3. **Webhook доставки** — `https://backend-production-f2a1.up.railway.app/auth/sms/status`. Сейчас не используется.
4. **Алерт при низком балансе.** Сейчас SMSC просто молча начнёт возвращать error 3 когда деньги кончатся, и юзеры перестанут получать коды без предупреждения.

**Известные TODO из аудита 07.05.2026 (не блокеры, отложено):**
- `services.py:474-492` — verification_id всё ещё возвращается клиенту даже если SMS не отправилась (выбор Q2=C при ревью). Низкий риск утечки кода, но если когда-нибудь поднимется Telegram dev fallback — пересмотреть.
- `services.py:461` — `range(100000, 999999)` исключает 999999 (off-by-one). Криптографически нерелевантно (900k вариантов), но симптом code review gap.
- `services.py:588` — `complete_register` хардкодит `platform=CodePlatform.WHATSAPP` хотя юзер пришёл по SMS. Audit trail врёт. Надо читать platform из verification metadata.
- Phone normalization расходится: `sms_client._normalize_phone` (`77XXXXXXXXX`) vs `services._normalize_phone_for_search` (`+77XXXXXXXXX`). Если юзер введёт `8707…` (старый формат) — SMSC ОК, но lookup сломается.

---

#### Историческая справка (что было до 07.05.2026)

Код связи backend ↔ SMSC работал в DEBUG-режиме, коды симулировались и писались в Deploy Logs.

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

**⚠️ Зависимость от клиента (07.05.2026):** Flutter-клиент в [register_user_remote_source.dart](lib/features/auth/data/sources/register_user_remote_source.dart) и [reset_password_remote_source.dart](lib/features/auth/data/sources/reset_password_remote_source.dart) сейчас отправляет `"platform": "sms"` (изменено с `"whatsapp"` 07.05.2026 при активации SMSC прода — Wazzup был в DEBUG-режиме и тихо «глотал» все коды). Когда Wazzup поднимется в прод:
1. Вернуть в обоих файлах `"platform": "whatsapp"` (или сделать UI-выбор канала)
2. Либо в backend — умный fallback: при `platform=WHATSAPP` и `WAZZUP__DEBUG=true` автоматически использовать SMS
3. Либо роутер: всегда WhatsApp first, SMS fallback при ошибке Wazzup (требует переписать `_send_confirmation_code`)

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

### M3. Изолированный testcontainer-стейдж (отложено в postпрод 04.05.2026)

**Текущее состояние (04.05.2026):** ✅ pytest job уже **BLOCKING**, 38 тестов проходят на каждом PR (22 unit + 4 service-layer + 12 smoke). Тесты живые против Railway prod через httpx.

**Что НЕ закрывает текущая инфраструктура:**
- Тесты делают реальные SMSC DEBUG calls и Keycloak grants — на CI runner это OK (DEBUG mode, без денег), но в идеальной схеме должны быть моки.
- Если Railway упадёт — все CI зелёные превратятся в красные хотя код OK.
- Сервисный слой покрыт только частично: `AuthService.login` (4 unit), `FreedomPay HMAC` (10 unit), `Google OAuth audience` (6 unit), `_real_client_ip` (5 unit), `cache_keys` (5 unit). НЕ покрыто: `FamilyService` permissions/invitations/role-checks, `EntAttemptService` подсчёт балла, `PaymentService.process_callback` бизнес-логика, `SubscriptionService.is_active`, `CashbackService`, `AttendanceService`, `DailyTestService`, `QuestionService`.

**Что включает M3 (4-6 часов работы):**

1. **testcontainers**: Postgres + Redis в Docker, поднимается в `conftest.py` сессионно. Каждый тест получает чистую БД.
2. **Моки внешних сервисов**: Keycloak (через `respx` для HTTP-моков), Resend (capture'ed emails), SMSC (capture'ed codes), Firebase (no-op stub).
3. **+20-30 unit-тестов на сервисный слой:**
   - `FamilyService.send_invitation` — все правила (cannot-invite-self, parent↔child only, no duplicates, transitions pending→confirmed/rejected)
   - `FamilyService.respond_to_invitation` — accept/reject paths
   - `EntAttemptService.create` — full-exam vs subject, deadline calculation, existing active attempt detection
   - `EntAttemptService.answer` — score calculation, points granted only when score>0
   - `PaymentService.process_freedompay_callback` — happy path + invalid signature rejection + duplicate-callback dedup
   - `SubscriptionService` — FREE/LITE/PRO transitions, expiry handling
   - `CacheService.@cached` — decorator behaviour (cache hit, cache miss, params change)
4. **Снять `continue-on-error: true`** с format-check (последний advisory job).

**Зачем отложено:** текущее состояние достаточно для прод-релиза для базовой нагрузки. M3 — это скейл-задача для момента когда у нас будет много контрибьюторов / много изменений в день. Сейчас приоритет ниже (acceptance tests от 4-6h, лучше потратить эту инвестицию когда станут видны конкретные регрессии).

**Кто берёт:** один разработчик за один заход в 4-6 часов. Можно делать частично — каждые 5 unit-тестов в отдельный PR.

---

### M4. ruff full-strict re-enable (after legacy cleanup)

**Сейчас (PR #26):** ruff config в `pyproject.toml` сильно урезан — оставлены только `E + F + W` правила (syntax errors, undefined/unused names, deprecation). Отключены `I/UP/B/SIM/T20/G/YTT/S/C4/ARG` потому что Романовский legacy код имел 89+ нарушений и каждый PR блокировался бы.

Также в ignore list:
- `E402` (import not at top) — у нас logger placement legacy в нескольких файлах
- `F401`, `F811` — DI plumbing pulls names that look unused statically

**Когда вернуть:**
1. Запустить `ruff check src --fix` — половина ошибок (`I001 imports order`) починится автоматически.
2. Остальные (`B*`, `S*`, `T20`) — пройти руками файл за файлом, ~2-4 часа.
3. Снять урезание из `pyproject.toml`, вернуть полный select.
4. Снять `continue-on-error: true` с ruff job в `.github/workflows/ci.yml`.

После этого CI начинает блокировать стиль-нарушения и security-хинты на новых PR.

---

### M2. CI cleanup — fix legacy ruff warnings + bump deps with security patches

**04.05.2026 update:** CVE-bumps **закрыты** в PR #26 (12 known vulnerabilities → 0). pip-audit job переведён в BLOCKING — новые CVE-подверженные deps больше не пройдут. Ruff cleanup отложен в M4 (выше).

(Историческая запись ниже сохранена для контекста.)

**Сейчас:** GitHub Actions `ci.yml` (PR #16) запускает 4 чека на каждый PR:
- ✅ `byte-compile` (blocking) — pure syntax pass on `src/` + `alembic/`
- ✅ `alembic-heads` (blocking) — exactly one alembic head, no diverging migration branches
- ⚠️ `lint` (advisory, `continue-on-error: true`) — ruff check + format
- ⚠️ `security-audit` (advisory, `continue-on-error: true`) — pip-audit `--strict`

`continue-on-error` оба advisory чека потому что existing legacy code на момент 04.05.2026 имел:
- ~150 ruff warnings из Романовского era (E402 import-not-at-top, I001 unsorted imports, S* security hints).
- 12 known CVEs в pinned deps (starlette 0.41.3 → 0.49.1, requests 2.32.3 → 2.33.0, python-multipart 0.0.20 → 0.0.26, и др.).

**Задачи перед prod:**

1. **Зачистить ruff warnings** (1-2 часа):
   ```bash
   ruff check src --fix  # auto-fixable: I001 sort, format issues
   ruff check src         # вручную пофиксить остаток (E402, S*)
   ruff format src        # унифицирует style
   ```
   После — снять `continue-on-error: true` с lint job.

2. **Bump deps c security patches** (1 час):
   - В `requirements.txt` поднять: `starlette` → `0.49.1+`, `requests` → `2.33.0+`, `python-multipart` → `0.0.26+`, и остальные из `pip-audit` отчёта.
   - `pip-audit -r requirements.txt --strict` локально → должно быть зелёным.
   - После — снять `continue-on-error: true` с security-audit job.

После этих двух шагов CI становится **полностью blocking** — ни один PR не пройдёт без чистого lint + 0 known CVE. Это правильное состояние для prod.

---

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

### 29. TestFlight build 14 — собран, не залит

**Status:** ⏳ ожидает аплоада

**Что готово:** локально собран IPA `build/ios/ipa/AIMA.ipa`, версия
**1.2.0+14**. Подтверждена корректность entitlements:

```
codesign -d --entitlements - Payload/Runner.app
→ application-identifier = 682LNLFMMN.kz.aima.aima
→ aps-environment        = production    ✓
→ (applesignin отсутствует, как и должно после d3dcf08)
```

**Что в этой сборке относительно build 12 (последней залитой 8.05.2026):**
- LaTeX render safety + post-test logout fix (`f5e8287`)
- Lumi → AIMA полная зачистка двух слоёв (`9e262f9`, `582176a`)
- Apple + Google Sign-In удалены, только phone+SMS (`d3dcf08`)
- PRO badge + кристалл сняты с главного экрана (`657d5e5`)
- Android perms: POST_NOTIFICATIONS + CAMERA + дроп OAuth deep-link (`44da2d8`)
- iOS APNs entitlement подключен, push заработает (`fbba69e`)

**Что юзер должен сделать:**
1. Открыть Transporter
2. Drag-n-drop `build/ios/ipa/AIMA.ipa`
3. Deliver — загрузка ~3-5 мин
4. Подождать ~10-30 мин обработки в App Store Connect
5. Билд появится в TestFlight → iOS Builds со статусом Ready to Test
6. На iPhone в TestFlight: pull-to-refresh → Update

**Build 13 в TestFlight (если ещё там):** игнорировать, в нём нет APNs
entitlement → iOS push не работает. Build 14 его перекрывает.

**Status:** ⏳ ожидает аплоада в TestFlight (отложено решением 2026-05-09:
«проверим чуть позже, пока запиши в тех долг»).

---

### 30. Ротация засвеченных секретов — постпрод

**Контекст 09.05.2026:** во время прод-аудита 8 секретов были вставлены
в чат с ассистентом одним блоком (env-paste). Технически — leak-канал
ограничен (single-tenant assistant, no public exposure), но best
practice требует ротации после любой утечки.

**Что закрыто (10.05.2026):**
- ✅ Apple `.p8` Sign-In key (`F63F33HT4L`) — revoked
- ✅ Firebase Service Account JSON — revoked + новый `b86a84456b14...`
- ✅ Google OAuth Client Secret — added new + старый удалён

**Что отложено в постпрод:** 5 секретов остались с засвеченными значениями.
Решение 10.05.2026: «не блокирует ревью App Store/Play Store, фокус на
прод-релизе, ротация — после стора».

| Secret | Risk if abused |
|---|---|
| `keycloak__admin__PASSWORD` | Полный контроль над юзерами/realm — самое опасное |
| `keycloak__open_id__CLIENT_SECRET_KEY` | Подделка токенов авторизации |
| `SMSC__KEY` | Спам SMS, дренаж бюджета (~$5-50/час) |
| `freedom_pay__SECRET` | Подделка платёжных коллбэков |
| `email_client__API_KEY` (Resend) | Спам с домена `aima.kz`, попадание в blacklist |

**Когда ротировать:** в первый рабочий день после прод-релиза. Каждый
секрет — 5-10 мин:

1. **Keycloak admin** — admin UI → My Account → Update Password →
   обновить `keycloak__admin__PASSWORD` в Railway сервисе backend
   **И** `KEYCLOAK_ADMIN_PASSWORD` в Railway сервисе keycloak.
2. **Keycloak open_id** — Keycloak admin → Realms → lumi → Clients →
   web-app → Credentials → Regenerate Secret → залить в
   `keycloak__open_id__CLIENT_SECRET_KEY`.
3. **SMSC** — личный кабинет smsc.kz → сменить пароль API → залить в
   `SMSC__KEY`.
4. **FreedomPay** — связаться с support → запросить ротацию Merchant
   Secret → залить в `freedom_pay__SECRET`.
5. **Resend** — resend.com → API Keys → revoke старый → create new →
   залить в `email_client__API_KEY`.

**Status:** ⏸ отложено в постпрод (фокус на App Store / Play Store
review).

---

### 28. Postgres backups — апгрейд Railway на Pro plan

**Почему важно:** на Hobby plan встроенные Daily Backups недоступны
(Railway: «Backups are only available for customers on the Pro plan»).
Сейчас бэкапов **нет**. Любая косячная миграция или `DROP TABLE` →
безвозвратная потеря всех аккаунтов, тестов, прогресса.

**Решение:** апгрейд проекта `content-inspiration` на Pro plan
($20/мес). После апгрейда:

1. Postgres → **Backups** tab → Enable **Daily Backups** + retention 7 дней.
2. (Опционально, в Pro plan) **Point-in-Time Recovery** — откат на любую секунду в течение 7 дней.
3. Нажать **Run Backup Now** один раз → проверить что снапшот создался.

**Альтернатива (бесплатно, если откладываем апгрейд):** DIY-бэкап:
- Создать Railway Cron-сервис который раз в сутки делает `pg_dump $DATABASE_URL | gzip > backup.sql.gz` и заливает в существующий MinIO bucket.
- Retention чистить ручным cron старше 7 дней.
- Нет PITR, нет hot-восстановления, ~30-60 мин работы.

**Решено 2026-05-09:** откладываем на момент когда апгрейд оправдан (после первого прод-релиза + первой когорты юзеров). До этого момента — рисковая зона; стараться не делать опасных миграций без `BEGIN;...ROLLBACK;` в локальной копии.

**Status:** ⏸ отложено в постпрод — апгрейд при выходе в прод.

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

### 31. Медленная загрузка экранов (5-7 секунд)

**Симптом:** заметил юзер 11.05.2026 — переходы между экранами в TestFlight приложении подтормаживают на 5-7 секунд. На реальном iPhone из Казахстана.

**Причины (по убыванию вклада):**
1. **Railway хостится во Франкфурте** — каждый HTTP-запрос из KZ имеет RTT ~200-300 мс. Если экран дёргает 3-4 endpoint'a последовательно — секунда сразу есть.
2. **Keycloak дёргается дважды на каждый аутентифицированный запрос** — verify token + fetch user attributes. То есть для одного экрана: 4 endpoint'a × 2 Keycloak-hop = 8 round-trip'ов.
3. **`_find_user_by_phone` делает O(n) fallback**: «Fallback: scanning 19 users from Keycloak» в логах. Сейчас 19 юзеров — fallback занимает 240 мс. На 1000+ юзерах будет ~10 секунд.
4. **Нет кэша на стороне клиента**: `getPlans()`, `getBenefits()`, `getUser()` зовутся при каждом входе на экран без TTL-кэша в Flutter.
5. **Аватары не кэшируются на CDN** — каждый раз MinIO presigned URL → MinIO → клиент.

**Как чинить (от лёгкого к тяжёлому):**
- 🟢 **Frontend-кэш через `ObjectBox`/`flutter_secure_storage`** для статичных данных (plans, benefits, user profile) с TTL 5-15 мин. ~2 часа работы.
- 🟢 **Lazy-load в Flutter**: не блокировать UI пока ждём API, показывать skeleton-shimmer. ~3 часа.
- 🟡 **Cloudflare в виде прокси** перед Railway → edge-кэш ответов, gzip, HTTP/3. ~1 день настройки.
- 🟡 **Reverse-index в Keycloak** на attribute `phone` (Keycloak realm setting) → убирает O(n) fallback. Требует пересоздания realm или ручного SQL — рискованно, лучше после релиза.
- 🔴 **Перенести Keycloak ближе к KZ** (Azure Astana / Yandex Almaty) — большая миграция, +2-3 дня.

**Приоритет:** 🟡 не блокер релиза, делать в течение 1-2 недель после прода.

---

### 32. Юзера выкидывает на экран регистрации без причины

**Симптом:** юзер залогинен, через какое-то время (часы / на следующий день) при открытии приложения видит экран регистрации. Все локальные данные «теряются».

**Причины:**
1. **Access token Keycloak TTL = 5 минут** (default). При запросе interceptor пробует refresh-токен. Если refresh-токен тоже истёк (default 30 мин) — авто-логин невозможен.
2. **Refresh-токен TTL слишком короткий** — на проде обычно ставят `Session Idle = 7 days` / `Session Max = 30 days` в Realm Settings → Tokens.
3. **На iOS в TestFlight**: при переустановке билда (с Build 17 на 18, 19, 20) `flutter_secure_storage` иногда теряет ключи из Keychain — токены пропадают.
4. **Railway передеплои Keycloak** (если меняли realm.json) → все старые токены инвалидируются мгновенно.
5. **`flutter_secure_storage` без `accessibility` параметра** — на iOS дефолт `kSecAttrAccessibleWhenUnlocked`, после рестарта iPhone может терять токены.

**Как чинить:**
- 🟢 **Увеличить TTL refresh-токена в Keycloak**: Realm `lumi` → Tokens → SSO Session Idle = 30 дней, SSO Session Max = 90 дней. ~5 мин в админке Keycloak.
- 🟢 **Логировать причину разлогина в Flutter** — сейчас интерцептор молча редиректит на регистрацию. Добавить debugPrint когда refresh падает. ~30 мин.
- 🟡 **Поправить `flutter_secure_storage`** — добавить `iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock)` чтобы ключи переживали рестарт. ~15 мин.
- 🟡 **Прод-сборка через App Store** не страдает от переустановки TestFlight — это специфично для TestFlight-цикла. После релиза проблема сама уйдёт частично.

**Приоритет:** 🟡 не блокер релиза (Apple не будет проверять auto-logout на 24-часовом интервале), но крайне неприятно для юзеров. Делать в течение 1 недели после прода.

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

## 🛡️ Security tech debt — отложено из аудита 15.05.2026

В этот день мы прошлись по 7 категориям угроз и закрыли SMS-pumping
(global cap + per-IP block, оба admin-editable), brute-force на
`/code/check` (progressive delay), и trial-per-phone abuse
(phone-hash blacklist). Эти 3 пункта закрывают самый горячий риск —
"SMS бюджет улетит за ночь". Остальное явно отложили — здесь
описание чтобы следующая сессия не теряла контекст.

### SEC-1. Account Takeover (Q4) — отложено

**Симптомы которые надо отследить:** угнанный пароль через
credential stuffing, SIM-swap для PRO-юзеров, дать другу аккаунт
а потом поссориться.

**Что нужно сделать (одно или комбинация):**
- (A) Уведомление push/email при логине с нового User-Agent или IP/города.
  Без friction для legitimate users, мощный сигнал для жертвы ATO.
- (B) Force password reset через SMS на исходный номер если за час
  набралось 5+ failed logins с разных IP.
- (C) 2FA по email при критичных действиях (смена номера, отписка,
  смена пароля).
- (D) Проверить что `refresh_token` действительно ротируется на каждом
  `/auth/refresh` и старый инвалидируется.

**Кейс который пугает:** PRO-юзер ушёл на каникулы, SIM забрали через
SIM-swap, переоформили пароль → перехват аккаунта с активной подпиской.

**Скоуп проработан 16.05.2026 — отложен повторно до пост-ревью окна.**
Решение оператора: не трогать auth/fraud-слой пока идёт Apple Review build 22,
вернёмся следующим обновлением проекта. Согласованный MVP-скоуп для будущей
реализации:
- Канал уведомления: email юзеру + email админу (ppechkin574@gmail.com).
  Push/SMS отложили — у юзеров email уже собирается, FCM/APNs для юзер-сайда
  не настроен, SMS дорого.
- Refresh token rotation: **не пишем свой код** — включить в Keycloak
  `Realm Settings → Tokens → Revoke Refresh Token = ON`. Это config-change,
  не deployment. 30-дневный expiry уже работает по дефолту.
- Скоуп: backend-only (новая таблица `login_events`, hook в `/auth/login` +
  social callbacks, email-алерт при новом fingerprint). UI «Мои сессии» в
  профиле — отдельный future-task на Windows-сторону (Flutter Android).
- Триггер: каждый успешный логин (password + Google + Apple callbacks), не
  только refresh.
- Детекция «нового устройства» — **пропускаем для MVP**, гайки сейчас не
  закручиваем. Когда вернёмся, оцениваем по City+UA (GeoIP) или ждём
  стабильного device-id от мобильного клиента.

### SEC-2. Apple IAP receipt validation hardening (Q6) — отложено

Сейчас `/payments/apple/verify` валидирует receipt через Apple
`/verifyReceipt`. Это правильно, но есть 4 нюанса которые надо
проверить + добавить:

- (A) **Production-only validation** — проверить что наш код принимает
  receipt только из production env Apple, а не sandbox (или
  принимает оба, но различает их в БД).
- (B) **Same-receipt rejection** — если юзер reinstall'нул и тот же
  `transaction_id` повторно прислан → не выдавать PRO повторно
  (idempotency check).
- (C) **Bundle ID match** — после verify Apple возвращает `bundle_id`.
  Должно совпасть с `kz.aima.aima`, иначе отвергать.
- (D) **Server-to-server notifications (App Store Server Notifications V2)** —
  ✅ **КОД ГОТОВ 16.05.2026, не задеплоен — ждёт вердикта Apple build 22.**

  Ветка: `feature/sec-2-apple-s2s` (коммит `a3f5cff`, **не запушен**).
  Что добавлено: alembic-миграция `f7d3a1b9e8c4` (две таблицы —
  `apple_subscriptions` для маппинга user↔originalTransactionId,
  `apple_notifications` как inbox с idempotency по notificationUUID),
  новый сервис `payments/apple_s2s.py` (verifier по Apple Root CA G3 +
  handler с диспетчем DID_RENEW/EXPIRED/REFUND/REVOKE), эндпоинт
  `POST /webhooks/apple/notifications-v2`, обновление
  `/payments/apple/verify` чтобы сохранять (user_id ↔ original_transaction_id)
  при первой покупке. 36 unit-тестов (всего suite 179 passing).

  **Шаги мерджа после одобрения Apple build 22:**
  1. `git push origin feature/sec-2-apple-s2s`
  2. PR `feature/sec-2-apple-s2s → main`, мерджим.
  3. Railway автодеплоит main; на старте Alembic накатит `f7d3a1b9e8c4`.
  4. App Store Connect → App → App Store Server Notifications →
     Production Server URL = `https://backend-production-f2a1.up.railway.app/webhooks/apple/notifications-v2`.
     Аналогично Sandbox Server URL (для TestFlight + Xcode тестинга).
  5. Smoke: в Sandbox Apple шлёт `TEST` notification — должна прийти
     в `apple_notifications` со status='ignored'.

  **Шаги если Apple откажет (новый билд):** ветка остаётся, добавляем
  в неё SEC-1 и что Apple запросит, одним обновлением.

  Пункты (A)/(B)/(C) выше — отдельно от этой работы, остались
  отложенными:
  - (A) Production-only env check — текущий verifier различает
    Sandbox/Production по claim в JWS payload, оба принимает. ОК для
    мобильного приложения. Если захотим жёстко отвергать Sandbox в
    проде — добавить флаг в `AppleIAPVerifier.__init__`.
  - (B) Same-receipt rejection — на /verify сейчас просто повторно
    активирует subscription. Apple сам не даёт двойную charge'у, так
    что злоупотреблений нет, но idempotency check на
    `transaction_id` всё равно стоит добавить — TODO.
  - (C) Bundle ID match — `SignedDataVerifier(bundle_id=...)` уже
    enforce'ит на JWS path; на legacy /verifyReceipt path — нет.
    Добавить отдельным фиксом.

**Документация:** https://developer.apple.com/documentation/appstoreservernotifications

### SEC-3. FreedomPay fraud + chargeback handling (Q7) — отложено

Возможные атаки:
- Украденная карта → оплата → юзер получает PRO → реальный
  владелец делает chargeback → мы теряем деньги + комиссию.
- Webhook spoofing — атакующий шлёт fake callback что юзер «оплатил».

**Что нужно сделать:**
- (A) **3DS обязательная** для всех платежей через FreedomPay — снижает
  fraud на 90%, настройка на FreedomPay side.
- (B) **HMAC signature на webhooks** — проверить что наш код в
  `/api/routes/payments/webhook.py` валидирует подпись от
  FreedomPay (по `freedom_pay__SECRET`). Если нет — добавить.
- (C) **Chargeback handler** — FreedomPay шлёт нам callback о
  chargeback / dispute. Получили → деактивируем PRO у юзера,
  флаг для review. Сейчас может быть не обработано.
- (D) **Daily payment limit per user** — не более 3 успешных платежей
  в день на юзера. Опционально.

### SEC-4. Captcha (отказались) и leaderboard scraping

- **Captcha** — пользователь явно отказался в Q10. Оставляем
  rate-limit'ы основной защитой.
- **Leaderboard data leak** — endpoint `/leaderboard` возвращает имя
  + балл всех юзеров. Если кто-то скрапит — выкачивает базу
  юзернеймов. Минимум: показывать `first_name + initial.` вместо
  полного имени. Можно отложить.

### SEC-5. KZ-only phone enforcement в SMS-клиенте

Бэкенд-уровень: `auth/services.py` валидирует `^\+77\d{9}$` через
regex. Дополнительно стоит добавить второй фильтр прямо в
`SMSCClient.normalize_phone` — отбрасывать любой нормализованный
номер не начинающийся с `77`. Это защита от случайной отправки на
не-KZ номер (если, скажем, валидатор обойдут через CHANGE_EMAIL flow
с phone в поле email).

**Договорная привязка:** п. 6.7 договора SMSC №764167 — штраф 500 ₸
за каждое SMS или 1 000 000 ₸ при международном трафике от
национального имени. Защита defense-in-depth обязательна.

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

---

## 🗺️ Roadmap to Production — аудит 07.05.2026

> Полный системный аудит mobile-приложения, бэкенда и админки на предмет заглушек, незаконченной логики и сервисов в нерабочем/тестовом режиме. Составлен 07.05.2026 после iOS-сессий.

### Приоритет 1 — БЛОКЕРЫ ПРОДАКШНА

Без этих пунктов запуск технически невозможен / нарушаются правила сторов.

| # | Пункт | Где | Что делать |
|---|---|---|---|
| 1 | ✅ **SMS реально отправляются** (закрыто 07.05.2026) | Backend SMSC активирован в проде | Баланс пополнен (~1010 ₸), `SMSC__DEBUG=false`, frontend переключен на `platform=sms`, баг `apikey→psw` починен, security-аудит пройден (`block_key`, маскировка кода в логах). См. секцию 8. |
| 2 | ✅ **FreedomPay платежи проходят** (закрыто 07.05.2026) | Форма vue-tel-input приняла submit и провела платёж до экрана успеха | Раcкрыли через `pg_user_country=KZ` + `pg_currency=KZT` + реальный IP вместо `127.0.0.1` + удаление `pg_skip_user_form` + перевод `pg_testing_mode` в env. Подтверждено E2E: payment_id `1761666995` 4990 KZT, webhook `/fp/result_notify` дошёл, Keycloak обновлён в PRO. См. коммит `7612d35` и секцию 6. **Малый UX-долг:** клиент не рефрешит токен после оплаты, юзеру надо выйти-зайти чтобы увидеть PRO статус. |
| 3 | ✅ **Cancel subscription реально работает** (закрыто 07.05.2026) | `subscription_profile_screen.dart` | Backend-эндпоинт `/user/subscription/cancel` + клиентская UI с disabled-state «Подписка отменена. Активна до...». 2 бага найдены и починены через дополнительный аудит (DioException parsing + post-cancel UI). |
| 4 | ✅ **Удалить остатки бренда «Lumi» из UI** (закрыто 06.05.2026) | `app_localizations*.dart` | Заменены на AIMA, AI-teacher tab скрыт. См. коммит `63997bf`. |

### Приоритет 2 — ВАЖНО, НЕ БЛОКЕР

| # | Пункт | Текущее состояние | Что делать |
|---|---|---|---|
| 5 | **Wazzup (WhatsApp-коды)** | env `WAZZUP__API_KEY=changeme`, `WAZZUP__TEMPLATE_ID=changeme`, `WAZZUP__DEBUG=true` | Завести в кабинете Wazzup24 + получить API key/template ID. Альтернативный канал кодов на случай если SMS лагает. |
| 6 | **Telegram-бот алертов админам** | env `telegram_bot__TOKEN=changeme` | Создать бота через `@BotFather`, прописать в env. Используется для уведомлений о критичных ошибках бэкенда. |
| 7 | **Sentry error tracking** | env `SENTRY_DSN` не установлен | Создать проект на Sentry.io, прописать DSN в Railway env. Сейчас все ошибки видны только в Railway logs (которые трудно искать). |
| 8 | **Cloudflare Stream** (если используется для видеоуроков) | env `cloudflare_customer_code=changeme` | Если фича видео-уроков планируется в проде — настроить Cloudflare Stream аккаунт. Если нет — выпилить интеграцию. |
| 9 | **Admin panel** | Задеплоен на Railway (Online), но git локально показывает только `init`+`gitignore` (203 файла без истории) | Проверить что Roman/админ может зайти, протестировать CRUD-операции, настроить роли. |
| 10 | **Backend TODOs** | `src/quiz/services/modules.py:1399` `start_score=0  # TODO: get from progress` | Реализовать чтение start_score из progress/test_results вместо хардкода. Влияет на корректность стартового балла модуля. |
| 11 | **`training_screen.dart` пустой initState** | `aima-app/lib/features/training/presentation/screens/training_screen.dart:30` `// TODO: implement initState` | Проверить нужен ли — возможно экран не загружает данные при первом открытии. |
| 12 | **Захардкоженные mock-данные в Statistics** | `aima-app/lib/features/statistics/presentation/screens/statistics_screen.dart` — массив `[15.0, 25.0, ...]` для mini-bar-chart в карточке «Ср. время» | Заменить на реальные данные из `state.globalStatistics` или скрыть карточку до готовности фичи. |
| 13 | **Лидерборд** | Empty state «Лидерборд скоро появится» | Реализовать backend-эндпоинт + UI. Сейчас юзеру обещают, что появится — но никто не работает над фичей. |

### Приоритет 3 — ЖЕЛАТЕЛЬНО

| # | Пункт | Действие |
|---|---|---|
| 14 | Balance pill на Profile/Home (скрыт коммитом `ee004b9`) | Решить: вернуть когда фича готова или удалить из кода |
| 15 | Universities/specialties recommendations | Placeholder «Эта функция ещё в разработке... 🎉» — доделать или убрать |
| 16 | Family/QR feature | Placeholder «А пока вы можете добавить через QR-код» — доделать. **07.05.2026:** плитка «Моя семья» в Профиле временно заглушена (`Скоро` badge + snackbar при тапе) — в коммите `e4aac35` aima-app. FamilyScreen и AddFamilyScreen остались в кодбейзе, но недоступны через UI. Восстановить можно одним коммитом — вернуть `_mockFamilyMembers` + GestureDetector → `/profile/family` в `profile_screen.dart::_buildFamilyTile`. До этого нужен реальный backend для приглашений / ролей parent-child / общей статистики семьи. |
| 17 | Bank card styles | TODO: добавить остальные стили карт (`bank_card.dart:181`) |
| 18 | Тестирование на Android | См. отдельный `ANDROID_GUIDE.md`. На Android приложение не тестировалось в этой сессии. |
| 19 | End-to-end автотесты для critical paths | Сейчас 22 unit/widget тестов; нет integration тестов на login → home → buy subscription |

### 📦 Контентные изменения (07.05.2026)

| # | Пункт | Что сделано |
|---|---|---|
| C1 | **Фичи подписки → редактируются через админку** | Бэкенд: новая таблица `subscription_benefits` (`title_ru`, `title_kz`, `description_ru`, `description_kz`, `position`, `is_active`), seed 6 RU+KZ из миграции `a1f0e7e3b4c2`. Endpoints: public `GET /content/subscription-benefits?lang=ru\|kz`, admin CRUD `/admin/content/subscription-benefits` (роль `admin`). Flutter: `SubscriptionBenefit` entity + `SubscriptionCubit.getBenefits()` с автоопределением локали (`kk*`/`kz*` → kz, иначе ru), `_resolveBenefits` использует state.benefits с fallback на хардкод. Админка: страница `/content/subscription-benefits` с CRUD + sidebar пункт. Локаль казахского — «понятное» качество, заказчик может полировать через UI. |
| C2 | Footer-ссылки → внешние документы на сайте | Раньше: `/privacy_policy` и `/terms_of_use` пушили на in-app пустые роуты. Теперь: открывают `https://www.aima.kz/docs.html#privacy` и `…#agreement` в новом `DocsWebViewScreen` (in-app WebView, требование Apple guideline 5.1.1). Коммит `e4aac35` aima-app. |

### Приоритет 4 — ХАРДЕНИНГ

| # | Пункт | Действие |
|---|---|---|
| 20 | Keycloak admin password | `gRv6grqO0OcQCnCCXRD4d2B90ZMsNquf` захардкожен в Railway env, никогда не ротировался. Сменить + перейти на Sealed variables. |
| 21 | Apple OAuth private key | В env как base64-строка (`apple_oauth__PRIVATE_KEY_PEM`). Хорошо что не volume-файл, но ротация не отлажена. |
| 22 | Backup стратегия Postgres | Включить Daily backups в Railway Postgres |
| 23 | Rate limiting | Есть на `/auth/code/request`, проверить остальные критичные endpoints (особенно `/auth/login`, `/user/subscription/create-payment`) |
| 24 | CORS | `allowed_origins` явный список — хорошо. Перепроверить что нет `*` в проде. |
| 25 | Sealed variables | Перевести секреты (Apple key, Google secret, FreedomPay secret) на Railway sealed |

### 📁 Где описаны полные процедуры

- iOS-сборка и тесты — `IOS_GUIDE.md`
- Android-сборка и риски — `ANDROID_GUIDE.md`
- FreedomPay блокер — секция 6 этого документа
- Бренд-перенос (что уже сделано) — коммиты `2a99a36`, `d30a8a6`, `608015d`, `b9bdb0a`, `e9c7f24`


