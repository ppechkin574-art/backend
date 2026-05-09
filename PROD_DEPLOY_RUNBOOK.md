# PROD-DEPLOY RUNBOOK

Шаги, которые **нельзя сделать кодом** — только через Railway dashboard. Делать **до** первого прод-релиза.

Дата составления: 2026-05-09. Если читаешь это позже — открой
[Railway Help](https://docs.railway.com) и сверь, не поменялся ли UI.

---

## 1. Включить бэкапы Postgres

**Зачем:** прямо сейчас бэкапов нет. Любая косячная миграция / rm -rf в БД =
безвозвратная потеря всех аккаунтов, тестов, прогресса.

**Где:** Railway → проект `content-inspiration` → service **`Postgres`** →
вкладка **Settings** → блок **Backups**.

1. Включить **Daily Backups** (бесплатно на Hobby plan, входит в Pro).
2. Поставить retention 7 дней.
3. (Опционально) включить **Point-in-Time Recovery** если на Pro plan —
   позволит откатиться на любую секунду в течение 7 дней.
4. После сохранения нажать **Run Backup Now** один раз — проверить, что
   первая копия успешно создалась (появится в списке снизу).

**Verify:** в списке Backups появится снапшот с временем «Just now».
В будущем Railway будет создавать его автоматически каждые 24 часа.

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

## 4. (Опц.) Включить Sentry

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
