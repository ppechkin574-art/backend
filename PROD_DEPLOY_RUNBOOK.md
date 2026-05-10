# PROD-DEPLOY RUNBOOK

Шаги, которые **нельзя сделать кодом** — только через Railway dashboard. Делать **до** первого прод-релиза.

Дата составления: 2026-05-09. Если читаешь это позже — открой
[Railway Help](https://docs.railway.com) и сверь, не поменялся ли UI.

---

## 1. Postgres backups — ⏸ отложено в постпрод

**Текущий статус (2026-05-09):** Hobby plan не даёт встроенные Daily
Backups (требуется Pro plan, $20/мес). Решено отложить апгрейд до
момента когда выйдем в прод и появится первая когорта юзеров.

**Что это значит сейчас:**
- Бэкапов **нет**. Любая косячная миграция или `DROP TABLE` →
  безвозвратная потеря всех данных.
- До прод-релиза стараться **не делать опасных миграций без
  локальной проверки** (`BEGIN; ... ROLLBACK;` в local-копии БД).
- Контент-дамп Романа (Postgres-таблицы тестов и вопросов) можно
  пересоздать из исходного файла, но user accounts (Keycloak) — нет.

**Когда апгрейдить на Pro:** в день когда первый реальный юзер
зарегистрируется в проде. До этого риск приемлемый.

**Полный план апгрейда** — TECH_DEBT.md секция 28.

---

## 2. Закрыть публичный доступ к Postgres

**Зачем:** сейчас Postgres имеет TCP Proxy наружу
(`postgres-production-XXXX.up.railway.app:NNNNN`). Любой, кто узнает
hostname:port, может пытаться брутфорсить. Прод БД должна быть доступна
только из приватной сети Railway, к которой подключён сервис `backend`.

**Где:** Railway → проект `content-inspiration` → service **`Postgres`** →
вкладка **Networking** → блок **Public Networking**.

1. Нажать **«Remove Domain»** (или toggle **Public Networking → Off**).
2. Убедиться, что **Private Networking** остался **включён** —
   `backend` дёргает БД именно по приватной сети.
3. Проверить переменную `DATABASE_URL` в сервисе `backend`: должна
   указывать на `postgres.railway.internal:5432` (приватный hostname),
   **не** на `*.up.railway.app:NNNNN`.

**Verify:** после применения попытка подключиться через `psql` снаружи
по старому host:port отвалится по таймауту. Прод-сервис продолжает
работать как раньше.

> ⚠️ Перед нажатием убедись, что у тебя есть локальная копия БД на
> случай если потребуется debug-доступ — после закрытия публичного
> доступа подключиться извне можно только через `railway connect Postgres`
> (создаёт временный туннель).

---

## 3. Установить `ALLOWED_ORIGINS` env-var

**Зачем:** в этом коммите (`src/api/__init__.py`) удалён wildcard-fallback
для CORS. Без явного значения переменной приложение **упадёт при старте**
с ошибкой `RuntimeError: ALLOWED_ORIGINS env var must be set...`.

**Где:** Railway → проект `content-inspiration` → service **`backend`** →
вкладка **Variables** → кнопка **+ New Variable**.

```
ALLOWED_ORIGINS = https://aima.kz,https://admin.aima.kz
```

(Замени список доменов на реальные. Мобильное приложение iOS/Android
делает запросы НЕ через браузер, ему CORS не нужен — только веб-фронт
и админка.)

**Verify:** после деплоя глянь логи — должна быть строка
`[rate-limit] limiter wired: …` без `RuntimeError`. Если есть RuntimeError —
переменная не подхватилась.

---

## 4. Reviewer-bypass для App Store / Play Store (ОБЯЗАТЕЛЬНО до Submit)

**Зачем:** Apple/Google ревьюеры физически в Купертино/Mountain View
не могут получить SMS через SMSC.kz. Без зарезервированного тестового
номера + фиксированного кода **submission будет отклонён 100%** —
guideline 2.1 «App must be functional».

**Где:** Railway → service **`backend`** → Variables.

```
REVIEWER_TEST_PHONE = +77001234567
REVIEWER_TEST_CODE  = 123456
```

После save Railway передеплоит за ~30 сек.

**Что меняется в backend (commit `<TBD>`):**

* `_is_reviewer_test_contact(contact)` возвращает `True` только когда
  `REVIEWER_TEST_PHONE` задан И совпадает с пришедшим номером.
* `request_code` для test-контакта:
  * пропускает «user already exists» (рев. может re-регаться повторно),
  * не дёргает SMSC.kz (нет траты SMS-бюджета),
  * пишет в Redis фиксированный код (`REVIEWER_TEST_CODE`, default
    `123456`).
* `check_code` — **без изменений**, существующий compare-with-Redis
  путь сам валидирует код.

**Почему это безопасно:**

1. Bypass дремлет когда env-переменные не заданы (`bool(...)` False) —
   локально/staging работает как раньше.
2. Worst-case утечка номера → 1 спам-аккаунт зарегается с trial.
   Никаких admin прав, никакого доступа к чужим данным.
3. Номер `+77001234567` — формат, не выдаваемый реальным kz-оператором.

**App Store Connect → App Review Information → Sign-In Required:**

```
Username: +77001234567
Password: 123456
Notes:    SMS не нужен. Введите телефон, нажмите «Отправить код»,
          затем введите 123456 — это reviewer-bypass для подтверждения
          без реальной SMS.
```

**Verify локально:**

```bash
curl -X POST $BACKEND/auth/code/request \
  -H 'Content-Type: application/json' \
  -d '{"contact": "+77001234567", "platform": "sms", "action": "register"}'
# → 200 OK, verification_id

curl -X POST $BACKEND/auth/code/check \
  -H 'Content-Type: application/json' \
  -d '{"verification_id": "<from above>", "code": 123456, "action": "register"}'
# → 200 OK, valid: true
```

---

## 5. (Опц.) Включить Sentry

**Зачем:** сейчас краши на проде ловишь только когда юзер жалуется.

**Где:** Railway → service **`backend`** → Variables.

```
SENTRY_DSN = https://...@sentry.io/...
```

Sentry SDK уже есть в коде (`api/__init__.py:_init_sentry`), он молчит
если `SENTRY_DSN` не задан. После установки переменной — рестарт сервиса.
Логи покажут `[sentry] initialised — env=production`.

---

## Чек-лист перед прод-релизом

- [ ] Postgres Daily Backups включены, первый снапшот создан
- [ ] Postgres Public Networking выключено
- [ ] `ALLOWED_ORIGINS` установлена с правильным списком доменов
- [ ] (опц.) `SENTRY_DSN` установлена
- [ ] `railway.toml` закоммичен (включает healthcheck `/health`)
- [ ] После деплоя проверить `https://backend-production-f2a1.up.railway.app/health`
      отвечает `{"status":"healthy",…}`
