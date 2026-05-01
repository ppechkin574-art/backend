# MinIO Setup — AIMA Backend

Пошаговая инструкция по разворачиванию MinIO на Railway и подключению backend.

**Цель:** заменить заглушки `localhost:9000 / minioadmin / minioadmin` на реальный MinIO. После этого заработают:
- Загрузка картинок к вопросам, вариантам, подсказкам.
- Загрузка аватарок и пользовательских файлов.
- Импорт пакета вопросов из Excel-файлов.
- Раздача файлов через presigned-URL.

Подход — точно такой же как заложил Роман в `.env.sample`: ставим официальный образ MinIO рядом с другими сервисами.

---

## Шаг 1. Развернуть MinIO на Railway

В Railway проекте `content-inspiration → production`:

1. Кнопка **`+`** → **Docker Image** → введи:
   ```
   minio/minio:latest
   ```
   Назови сервис **`minio`** (с маленькой m).

2. В сервисе `minio` → **Settings → Deploy → Custom Start Command** введи:
   ```
   server /data --console-address :9001
   ```

   Это запустит MinIO сервер с данными в `/data` и веб-консолью на порту `9001`.

3. В сервисе `minio` → **Settings → Volumes** → **+ New Volume**:
   - **Mount path:** `/data`
   - **Size:** 1 GB на старт (потом можно увеличить).

   ⚠️ **Volume критичен:** без него все файлы пропадут при каждом редеплое.

4. В сервисе `minio` → **Settings → Networking**:
   - Под **Public Networking** жми **Generate Domain** для **API** (порт `9000`).
     - Получишь URL вида `minio-production-xxxx.up.railway.app` — это для админ-консоли в браузере.
   - **НЕ генерируй** второй домен для консоли (`9001`) — она и так доступна через тот же домен по `/console` или мы зайдём через S3 API.

   ⚠️ Backend будет ходить через **внутреннюю сеть** `minio.railway.internal`, не публичный домен — это бесплатно (не считается egress).

5. В сервисе `minio` → **Variables → Raw Editor** вставь:

   ```env
   MINIO_ROOT_USER=aima_admin
   MINIO_ROOT_PASSWORD=GENERATE_STRONG_PASSWORD_HERE
   MINIO_BROWSER_REDIRECT_URL=https://<MINIO_PUBLIC_DOMAIN>.up.railway.app
   ```

   ⚠️ `MINIO_ROOT_PASSWORD` — сгенерируй сильный пароль (минимум 8 символов, лучше 16+). **Запиши** — будет нужен далее.

   ⚠️ Замени `<MINIO_PUBLIC_DOMAIN>` на свой домен из Шага 4 (без `https://` он не нужен — добавляется автоматически).

6. Дождись успешного деплоя. В Deploy Logs должно быть:
   ```
   API: http://0.0.0.0:9000
   Console: http://0.0.0.0:9001
   ```

---

## Шаг 2. Зайти в MinIO Console и создать bucket

1. Открой `https://<MINIO_PUBLIC_DOMAIN>.up.railway.app` в браузере.

2. Залогинься:
   - **Username:** `aima_admin`
   - **Password:** значение `MINIO_ROOT_PASSWORD` из Шага 1.

3. Слева **Buckets** → **Create Bucket**:
   - **Bucket Name:** `aima-uploads` (или `gymbro` если хочешь как у Романа в `.env.sample`).
   - Остальные настройки по умолчанию.
   - Жми **Create Bucket**.

---

## Шаг 3. Создать Service Account (Access Key + Secret) для backend

Не используй `MINIO_ROOT_USER` напрямую в backend — лучше отдельный ключ с ограниченными правами.

1. В MinIO Console → **Access Keys** → **Create Access Key**.

2. Откроется окно со сгенерированным `Access Key` и `Secret Key`.

3. **Скопируй оба** перед закрытием окна — secret больше нельзя посмотреть, только regenerate.

4. (Опционально) Жми **Set Policy** → выбери права read/write для `aima-uploads` — но дефолтные права service account уже подходят.

---

## Шаг 4. Подменить переменные в backend

В Railway → сервис `backend` → **Variables** найди и замени:

```env
minio__endpoint    = minio.railway.internal:9000
minio__access_key  = <Access Key из Шага 3>
minio__secret_key  = <Secret Key из Шага 3>
minio__bucket      = aima-uploads
```

⚠️ `minio__endpoint` указывает на **внутренний** домен (`*.railway.internal`) без `https://` и **с портом `:9000`** (API порт MinIO, не консоль).

⚠️ Обрати внимание — в коде используется `secure=False` (см. `src/clients/media_storage/client.py:43`), то есть HTTP. Это нормально для приватной сети Railway, но публичная раздача через presigned-URL должна происходить через тот же приватный endpoint, и backend будет вынужден потом разворачивать внешний URL отдельно. Это решение оставлено как есть, не меняем без необходимости.

После сохранения Railway автоматически перезапустит backend.

---

## Шаг 5. Проверить работу

1. Дождись `Active` у backend.

2. Открой `https://backend-production-f2a1.up.railway.app/docs`.

3. Найди эндпоинт **`POST /admin/questions/import`** (или **`POST /admin/subjects`** — в зависимости от того что есть). Это эндпоинт где файл реально передаётся.

4. Сначала залогинься через `/auth/login-swagger` (`admin@aima.kz` / `ChangeMeAdmin123!`) → скопируй `access_token`.

5. Сверху Swagger UI жми **Authorize** → введи `Bearer <access_token>` → Authorize.

6. Найди любой эндпоинт с загрузкой файла (там где параметр `file: UploadFile`) → попробуй залить какой-нибудь .xlsx или .png. Должен вернуться 200 OK.

7. Зайди в MinIO Console → bucket `aima-uploads` → должен появиться загруженный объект.

---

## Возможные проблемы

### `MediaStorageError: Failed to save media`
- Проверь что в Railway сервис `minio` в статусе **Active** (не Completed).
- Проверь что `minio__endpoint=minio.railway.internal:9000` (без `http://` и без `/`).
- Проверь что bucket `aima-uploads` существует в MinIO Console.

### `S3 connection failed: timeout`
- Backend смотрит в неправильный endpoint. Если у тебя на сервисе `minio` нет публичного домена — это ок, нужен только `*.railway.internal`. Но имя сервиса в плейсхолдере должно совпадать (`minio.railway.internal`).

### `Access Denied`
- Service account не имеет прав на bucket. Перейди в MinIO Console → Access Keys → твой ключ → Set Policy → дай права `s3:*` на bucket `aima-uploads`. Либо просто пересоздай Access Key — дефолтные права обычно достаточны.

---

## Что дальше

После того как MinIO подключён:

- ✅ Загрузка файлов через backend работает.
- ✅ Картинки в вопросах отдаются через presigned-URL.
- ⏸️ Резервные копии содержимого MinIO — отдельная задача (TECH_DEBT.md п. 19, бэкапы).
- ⏸️ Замена self-hosted MinIO на managed S3 (Cloudflare R2 / AWS) — опциональная оптимизация, не сейчас.

Когда MinIO работает — закрывай п. 2 в TECH_DEBT.md и переходим к Firebase (п. 3).
