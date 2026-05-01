# Keycloak Setup — AIMA Backend

Пошаговая инструкция по разворачиванию Keycloak на Railway и подключению backend.

**Цель:** заменить заглушки `https://example.com` в env-переменных на реальный Keycloak. После этого заработает регистрация/логин/refresh токенов.

---

## Шаг 1. Развернуть Keycloak на Railway

В Railway проекте `content-inspiration → production`:

1. Кнопка **`+`** (или правая кнопка на канве) → **Database** → **PostgreSQL**.
   - Это **отдельная** БД для Keycloak, не та что используется backend. Keycloak хранит в ней realms/users/clients.
   - Назови сервис `Postgres-keycloak` (чтобы не путать с основным `Postgres`).

2. Снова **`+`** → **Docker Image** → введи `quay.io/keycloak/keycloak:26.0`.
   - Назови сервис `keycloak`.

3. В сервисе `keycloak` → **Settings → Networking → Generate Domain** — получишь публичный URL вида `keycloak-production-xxxx.up.railway.app`. **Запиши его.**

4. В сервисе `keycloak` → **Settings → Deploy → Custom Start Command** введи:
   ```
   start --optimized --proxy-headers xforwarded --hostname-strict=false --import-realm
   ```

5. В сервисе `keycloak` → **Settings → Source → Build → Custom Build Command** оставь пустым (используем готовый образ).

6. В сервисе `keycloak` → **Variables → Raw Editor** вставь (заменив `<KEYCLOAK_DOMAIN>` на свой):

   ```env
   KEYCLOAK_ADMIN=admin
   KEYCLOAK_ADMIN_PASSWORD=GENERATE_STRONG_PASSWORD_HERE
   KC_DB=postgres
   KC_DB_URL=jdbc:postgresql://${{Postgres-keycloak.PGHOST}}:${{Postgres-keycloak.PGPORT}}/${{Postgres-keycloak.PGDATABASE}}
   KC_DB_USERNAME=${{Postgres-keycloak.PGUSER}}
   KC_DB_PASSWORD=${{Postgres-keycloak.PGPASSWORD}}
   KC_HOSTNAME=<KEYCLOAK_DOMAIN>.up.railway.app
   KC_HOSTNAME_STRICT=false
   KC_HTTP_ENABLED=true
   KC_PROXY=edge
   KC_HEALTH_ENABLED=true
   KC_METRICS_ENABLED=true
   PORT=8080
   ```

   ⚠️ `KEYCLOAK_ADMIN_PASSWORD` сгенерируй надёжный пароль (хотя бы 16 символов). **Запиши его** — будет использоваться backend.

7. Дождись успешного деплоя. В Deploy Logs должно быть:
   ```
   Keycloak 26.0 on JVM (powered by Quarkus ...) started in ...
   Listening on: http://0.0.0.0:8080
   ```

8. Открой `https://<KEYCLOAK_DOMAIN>.up.railway.app` в браузере. Должна открыться страница Keycloak с кнопкой **Administration Console**.

---

## Шаг 2. Импортировать realm `lumi`

1. На главной странице Keycloak жми **Administration Console** → залогинься как `admin` / `<KEYCLOAK_ADMIN_PASSWORD>`.

2. В верхнем левом углу выбери dropdown с realm (по умолчанию `master`) → **Create realm**.

3. На странице создания realm:
   - **Resource file** → нажми **Browse...** и выбери файл `docs/keycloak-realm-lumi.json` из этого репозитория.
   - Имя realm заполнится автоматически: `lumi`.
   - Жми **Create**.

4. После создания realm:
   - Будет создано 2 клиента: `web-app` (confidential) и `tesla-admin-panel` (public для админки).
   - Будет создан тестовый пользователь `admin@aima.kz` с паролем `ChangeMeAdmin123!` (temporary — попросит сменить при первом входе).
   - Будут созданы realm-роли `admin` и `user`.

---

## Шаг 3. Получить `client_secret` для `web-app`

1. В realm `lumi` → **Clients** → **web-app** → вкладка **Credentials**.

2. Поле **Client Secret** — нажми **Regenerate** (или скопируй текущее значение).

3. **Скопируй secret** — это значение пойдёт в backend как `keycloak__open_id__CLIENT_SECRET_KEY`.

---

## Шаг 4. Подменить переменные в backend

В Railway → сервис `backend` → **Variables → Raw Editor** найди и замени следующие переменные (остальные — оставь как есть):

```env
keycloak__admin__SERVER_URL          = https://<KEYCLOAK_DOMAIN>.up.railway.app
keycloak__admin__USERNAME            = admin
keycloak__admin__PASSWORD            = <KEYCLOAK_ADMIN_PASSWORD из Шага 1>
keycloak__admin__REALM_NAME          = lumi
keycloak__admin__USER_REALM_NAME     = master
keycloak__admin__CLIENT_ID           = admin-cli

keycloak__open_id__SERVER_URL        = https://<KEYCLOAK_DOMAIN>.up.railway.app
keycloak__open_id__REALM_NAME        = lumi
keycloak__open_id__CLIENT_ID         = web-app
keycloak__open_id__CLIENT_SECRET_KEY = <client_secret из Шага 3>
```

После сохранения Railway автоматически перезапустит backend. В Deploy Logs не должно быть ошибок при запросах к Keycloak.

---

## Шаг 5. Проверить работу

1. Открой `https://backend-production-f2a1.up.railway.app/docs`.

2. Найди эндпоинт `POST /auth/login-swagger`. Нажми **Try it out**.

3. Введи:
   - `username`: `admin@aima.kz`
   - `password`: `ChangeMeAdmin123!`

4. Должен вернуться ответ с `access_token` и `refresh_token`. Это значит — Keycloak подключён.

5. Используй полученный `access_token` для вызова `GET /user/profile` (или другого защищённого эндпоинта) — должен вернуть данные пользователя.

---

## Возможные проблемы

### `KC_DB_URL` не разрезолвается
- Проверь, что сервис Postgres называется именно `Postgres-keycloak` (или поправь `${{...}}` плейсхолдеры).
- Сервис Postgres должен быть в **том же** Railway-проекте.

### Keycloak не стартует — `Cannot connect to database`
- Postgres-keycloak ещё не успел подняться. Дождись `Online` статуса у обоих сервисов и сделай Restart у Keycloak.

### Backend ругается `Connection refused` или `400` от Keycloak
- Проверь, что `KC_HOSTNAME` совпадает с публичным доменом Keycloak.
- Убедись, что `KC_PROXY=edge` стоит — Railway работает через прокси.

### `401 Invalid client credentials` при логине
- `client_secret` не совпадает. Регенерируй secret в Keycloak Admin Console и подмени в backend.

### CORS-ошибки при попытке логина из Flutter / Admin
- В client `web-app` (или `tesla-admin-panel`) → **Settings → Web Origins** добавь нужные домены, либо `+` (наследовать от redirect_uris).

---

## Безопасность после setup

После успешного запуска:

1. **Сменить пароль `admin@aima.kz`** на сильный, не `ChangeMeAdmin123!` (он temporary, при первом логине Keycloak попросит сменить — выбери надёжный).

2. **Защитить master realm:** в Keycloak Admin Console → перейти в `master` realm → Users → `admin` → сменить пароль на ещё более надёжный.

3. **Включить email verification:** в realm `lumi` → **Realm settings → Login → Verify email = ON**, заполнить SMTP в **Realm settings → Email**.

4. **Включить self-registration** (если нужно): **Realm settings → Login → User registration = ON**.

5. **Brute force protection** уже включён в realm-config (см. JSON).

---

## Что делать дальше

После того как Keycloak подключён:

- ✅ Можно логиниться через `/auth/login-swagger`.
- ✅ Можно регистрировать пользователей через `/auth/registration/complete`.
- ⏸️ Social login (Apple, Google) пока не работает — нужна отдельная настройка (см. TECH_DEBT.md пп. 4-5).
- ⏸️ Email/SMS-коды подтверждения требуют настройки SMTP/SMSC (TECH_DEBT.md пп. 7-8).

Когда Keycloak настроен — закрывай п.1 в TECH_DEBT.md и переходи к Шагу 2 (MinIO/S3).
