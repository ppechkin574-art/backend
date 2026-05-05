# Production Domains Setup — AIMA

Пошаговая инструкция как привязать собственные поддомены `aima.kz` ко всем сервисам Railway.

**Создан:** 04.05.2026 после CORS-фикса.
**Кем выполняется:** заказчик (`ppechkin574-art`) на Hoster.kz + Railway UI. Бэк-разработчик может только подсказывать, не имеет доступа к DNS.

---

## Цель

| Сервис | Сейчас (Railway URL) | После (custom domain) |
|---|---|---|
| Backend API | `backend-production-f2a1.up.railway.app` | `api.aima.kz` |
| Admin Panel | `admin-production-4572.up.railway.app` | `admin.aima.kz` |
| Keycloak | `keycloak-production-0a0c.up.railway.app` | `auth.aima.kz` |
| MinIO | `minio-production-3f82.up.railway.app` | `cdn.aima.kz` |
| Лендинг (если будет) | — | `aima.kz` (root) + `www.aima.kz` |

После настройки фронт-клиенты ходят на свои поддомены, всё под одним брендом, и Railway-URL'ы можно отключить через ~1 месяц (для backward compat пока оставляем).

---

## Шаг 1. Hoster.kz — DNS-записи для всех поддоменов

1. Войди в Hoster.kz панель управления → раздел **DNS** для домена `aima.kz`.
2. Добавь следующие **CNAME**-записи:

| Type | Name | Value (TTL: 3600) | Привязан к |
|---|---|---|---|
| CNAME | `api` | `backend-production-f2a1.up.railway.app` | Backend |
| CNAME | `admin` | `admin-production-4572.up.railway.app` | Admin |
| CNAME | `auth` | `keycloak-production-0a0c.up.railway.app` | Keycloak |
| CNAME | `cdn` | `minio-production-3f82.up.railway.app` | MinIO |

⚠️ **Не забудь сохранить.** В Hoster обычно после добавления нужно нажать "Apply" внизу страницы.

3. **Проверка распространения** (через 5-10 мин):
   ```powershell
   nslookup api.aima.kz
   nslookup admin.aima.kz
   nslookup auth.aima.kz
   nslookup cdn.aima.kz
   ```
   Должны показывать что они CNAME-указывают на Railway-сервера.

---

## Шаг 2. Railway — привязать custom domain к каждому сервису

В Railway → проект `content-inspiration` → **production** environment.

### 2a. Backend
1. Open service `backend` → **Settings** → **Networking**.
2. Раздел **Custom Domain** → нажать `+ Add` → ввести `api.aima.kz` → Add.
3. Railway покажет статус "Pending verification". Через 1-3 мин (после DNS-распространения) станет "Active".
4. Railway автоматически выдаёт **TLS-сертификат** через Let's Encrypt — ничего вручную делать не надо.

### 2b. Admin
1. Open service `admin` → Settings → Networking → Custom Domain → `admin.aima.kz`.

### 2c. Keycloak
1. Open service `keycloak` → Settings → Networking → Custom Domain → `auth.aima.kz`.
2. **Дополнительно:** в Variables добавить:
   ```
   KC_HOSTNAME=auth.aima.kz
   ```
   (Без этого Keycloak будет редиректить юзеров на старый URL.)
3. Restart сервиса.

### 2d. MinIO
1. Open service `minio` → Settings → Networking → Custom Domain → `cdn.aima.kz`.
2. **Дополнительно:** в Variables backend (`backend` сервис) обновить:
   ```
   minio__public_endpoint="cdn.aima.kz"
   ```
   После этого MinIO presigned URLs будут на `https://cdn.aima.kz/aima-uploads/...` вместо текущего Railway URL.

---

## Шаг 3. Backend env vars — обновить URL'ы

В Railway → service `backend` → Variables → **Raw editor** → обнови:

```
allowed_origins="https://aima.kz,https://www.aima.kz,https://app.aima.kz,https://admin.aima.kz,https://api.aima.kz,https://admin-production-4572.up.railway.app,https://backend-production-f2a1.up.railway.app"
google_oauth__REDIRECT_URI="https://api.aima.kz/auth/oauth/google/callback"
google_oauth__FRONTEND_REDIRECT="kz.aima.aima://oauth2redirect"
apple_oauth__REDIRECT_URI="https://api.aima.kz/auth/oauth/apple/callback"
apple_oauth__FRONTEND_REDIRECT="kz.aima.aima://oauth2redirect"
freedom_pay__CALLBACK_URL="https://api.aima.kz/payments/callback"
keycloak__admin__SERVER_URL="https://auth.aima.kz"
keycloak__open_id__SERVER_URL="https://auth.aima.kz"
file_base_url="https://api.aima.kz"
minio__public_endpoint="cdn.aima.kz"
```

(Старые Railway URL'ы в `allowed_origins` оставлены для backward compat пока DNS пропагирует. Удалить через ~1 месяц.)

---

## Шаг 4. Google Cloud Console — добавить новый redirect URI

OAuth client редиректит на старый Railway URL — нужно **добавить** новый (не удалять старый, пусть оба будут):

1. https://console.cloud.google.com → project `aima-prod`.
2. Меню → Google Auth Platform → **Clients** → клик на `aima-backend-web` → Edit.
3. Authorized redirect URIs → `+ Add URI`:
   ```
   https://api.aima.kz/auth/oauth/google/callback
   ```
4. Save.

---

## Шаг 5. Admin Panel — обновить env build-time переменные

В Railway → service `admin` → Variables → Raw editor:

```
VITE_API_BASE_URL="https://api.aima.kz"
VITE_KEYCLOAK_URL="https://auth.aima.kz"
```

После Update Railway пересоберёт Vite-приложение с новыми URL'ами.

---

## Шаг 6. Mobile App — обновить `Constants.baseUrl`

В Flutter-репо `app/lib/core/secrets/constants.dart`:

```dart
static String get baseUrl => 'https://api.aima.kz';
```

Это идёт через PR в frontend репозитории. После merge — пересобрать APK и переустановить на эмулятор.

---

## Шаг 7. Resend — Email branding

Уже настроено: домен `aima.kz` Verified, отправка с `noreply@aima.kz`. Ничего менять не нужно.

---

## Шаг 8. SMSC — sender registration

Это отдельный пункт TECH_DEBT (8 SMSC.kz section), требует:
- Пополнить баланс (минимум 1000 ₸)
- Зарегистрировать sender `AIMA` (1-3 дня модерации)
- Снять `SMSC__DEBUG=true`

---

## Шаг 9. Firebase

Если планируется отдельный subdomain для FCM webhook — не нужен. Firebase Cloud Messaging работает через Google's APIs, не наши домены. Уже настроено.

Для **дополнительной верификации iOS push** можно добавить `apple-app-site-association` файл на `https://aima.kz/.well-known/apple-app-site-association` — но это для Universal Links, не для push.

---

## Шаг 10. Финальная проверка

После всех настроек:

```bash
# 1. Backend через custom domain
curl https://api.aima.kz/health
# expected: {"status":"healthy",...}

# 2. Keycloak через custom domain
curl https://auth.aima.kz/realms/lumi
# expected: realm metadata JSON

# 3. CORS preflight для admin
curl -I -X OPTIONS https://api.aima.kz/auth/login \
  -H "Origin: https://admin.aima.kz" \
  -H "Access-Control-Request-Method: POST"
# expected: 200 OK + Access-Control-Allow-Origin

# 4. CORS preflight для левого origin (должен заблокировать)
curl -I -X OPTIONS https://api.aima.kz/auth/login \
  -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: POST"
# expected: 400 Bad Request (origin not in whitelist)

# 5. MinIO image через CDN
curl -I https://cdn.aima.kz/aima-uploads/subjects/physics.png
# expected: 200 (или signed URL redirect)
```

---

## Откат

Если что-то сломается — каждый Railway сервис в Networking видит **обе** доменные записи (старый Railway URL + новый custom). Просто:
1. Удалить custom domain в сервисе → Railway сразу вернётся на default URL.
2. Откатить env vars в backend (заменить `https://api.aima.kz/...` на `https://backend-production-f2a1.up.railway.app/...`).
3. Удалить CNAME в Hoster.

---

## История

- 04.05.2026 — документ создан после CORS закрытия (`*` → whitelist) и FK constraints миграции.
