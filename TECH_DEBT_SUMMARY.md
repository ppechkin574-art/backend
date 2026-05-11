# AIMA — технический долг кратко

Все открытые задачи, отсортированные по критичности. Полные детали — в `TECH_DEBT.md` (backend) и `aima-app/TECH_DEBT.md` (Flutter).

Дата обновления: **11.05.2026**.

---

## 🔴 КРИТИЧНО (блокеры релиза / уже в работе)

Все закрыты или в активной работе:

| # | Задача | Состояние | Как чинить |
|---|---|---|---|
| 1 | Apple In-App Purchase | ✅ Готово, тестируется в Build 20 | Sandbox-test → submit |
| 2 | Иконка приложения | ✅ `aima` сиреневая на белом (Build 20) | — |
| 3 | Lumi → AIMA ребрендинг | ✅ Готово | — |
| 4 | PRO → Month переименование | ✅ Готово | — |
| 5 | Reviewer-bypass для SMS | ✅ Работает (`+77001234567 / 123456`) | — |
| 6 | App Store Connect Metadata | 🟡 Шаблон готов (`APP_STORE_FORM_FIELDS.md`), нужно заполнить | Скопировать из шаблона |
| 7 | Tax Category на подписке | ✅ `Software training material` | — |

---

## 🟡 ВАЖНО (после релиза iOS, в течение 1-2 недель)

| # | Задача | Что не так | Как чинить (кратко) |
|---|---|---|---|
| 8 | **Медленная загрузка (5-7 сек)** | Railway в EU + Keycloak делает 2 хопа на каждый запрос + нет кэша в Flutter | Frontend TTL-кэш для plans/benefits/user (2-3 ч) + Cloudflare прокси перед Railway (1 день) |
| 9 | **Юзера разлогинивает** | Refresh-токен живёт 30 мин по умолчанию + iOS Keychain теряет ключи между билдами | Увеличить TTL refresh-токена до 30 дней в Keycloak (5 мин) + добавить `iOptions` в `flutter_secure_storage` (15 мин) |
| 10 | **Android релиз** | Не сделано ничего: нет Google Play Console аккаунта, нет Google Play Billing, нет AAB | Купить аккаунт ($25) + интегрировать Google Play Billing (2-3 дня) — выбран Variant B |
| 11 | Apple Sign-In | Отложено по решению | Код готов, нужны creds (Key ID, Team ID, .p8) → Railway env |
| 12 | OAuth consent screen в Production mode | Сейчас `Testing` — только test-юзеры | Google Auth Platform → Audience → Publish app |
| 13 | Email-verification в Keycloak | Не включено | Realm `lumi` → Login → Email verification = ON + настроить SMTP |
| 14 | Sentry для error monitoring | Код готов, не подключён | Создать проект → DSN в Railway env |
| 15 | App Store ASO planning | Не начато | Подобрать ключевики, описать преимущества vs конкурентов |

---

## 🟢 ИНФРАСТРУКТУРА (после прод-релиза)

| # | Задача | Что не так | Как чинить |
|---|---|---|---|
| 16 | Кастомный домен (`api.aima.kz`, `app.aima.kz`) | Сейчас Railway-домены | CNAME в DNS + Railway custom domains |
| 17 | Postgres backups | Railway free plan = только ручные | Апгрейд до Pro plan ($20/мес) |
| 18 | Subject images заливка в MinIO | 10 файлов не залиты | `mc cp lumipack/subject_images/* aima/subjects/` |
| 19 | Wazzup (WhatsApp-уведомления) | Заглушки `changeme` | wazzup24.com → API key |
| 20 | Telegram-бот для алёртов | Заглушки `changeme` | @BotFather → token |
| 21 | Восстановить FCM-токен flow | Mobile не регистрирует токен после логина | Frontend задача: дёргать `/user/daily-tests/devices/token` после login |
| 22 | Ротация засвеченных секретов (5 шт) | KEYCLOAK_ADMIN_PASSWORD, MinIO root, MERCHANT_SECRET, Postgres, Redis | Сгенерить новые, обновить в Railway, перезапустить |
| 23 | Cloudflare CDN | Не настроено | Cloudflare proxy + page rules для кэша |
| 24 | CI/CD | Сейчас вручную через `git push` | GitHub Actions → Railway deploy |
| 25 | Sealed Variables (Railway) | Секреты в обычных env | Включить «Sealed» для критичных переменных |
| 26 | Rate limiting | Базовый SlowAPI, не настроен жёстко | Поднять лимиты на `/auth/*` (10 req/min) и `/payments/*` (5 req/min) |
| 27 | Auto-deploy с preview environments | Каждый PR делает свой environment | Railway PR Previews → подключить в Settings |
| 28 | Полное покрытие тестами | Сейчас почти нет | Unit + integration тесты на критичные endpoint'ы |
| 29 | Strict typing (Pylance / mypy) | Не настроено в CI | `mypy --strict` на CI + постепенно типизировать |
| 30 | Тесты на Flutter | Сейчас почти нет | bloc_test для cubit'ов + golden tests для UI |

---

## 📋 Уже закрытые крупные задачи

Документация-история (детали в `TECH_DEBT.md`):

- ✅ Keycloak поднят (01.05.2026)
- ✅ MinIO/S3 настроен (01.05.2026)
- ✅ Firebase Cloud Messaging (02.05.2026)
- ✅ Email через Resend (02.05.2026)
- ✅ SMS через SMSC.kz реальный (07.05.2026)
- ✅ Google OAuth end-to-end (04.05.2026)
- ✅ FreedomPay платёж прошёл E2E (07.05.2026)
- ✅ Реальные `aima.kz` правовые документы (Privacy, Terms, Offer, 4990 ₸ цена)
- ✅ Лидерборд + статистика (Romанov design)
- ✅ Admin panel (Users, Marketing dashboard)
- ✅ Apple IAP backend `/payments/apple/verify` + verifier (11.05.2026)

---

## Что делать в каком порядке

### Сейчас (до релиза iOS — ~эта неделя)
1. ✅ Закончить тест IAP в TestFlight (sandbox)
2. ✅ Заполнить App Store Connect страницу версии 1.0
3. ✅ Прицепить подписку + Build 20 к версии
4. ✅ Submit for Review
5. ⏳ Ждать Apple одобрения (24-48 ч)
6. ⏳ Manual Release

### После релиза iOS (следующая неделя)
7. Android: Google Play Console + Google Play Billing (Variant B)
8. Auto-logout fix (#9 — увеличить TTL Keycloak)
9. Speed fix #1 (#8 — Flutter TTL-кэш для plans/benefits)

### Postпрод (1-2 недели после)
10. Cloudflare CDN + кастомный домен
11. Postgres backups (Pro plan)
12. Wazzup + Telegram alerts
13. Apple Sign-In
14. OAuth consent screen в Production
15. Email-verification в Keycloak

### Долгий хвост (1+ месяц)
16. Тесты (backend + Flutter)
17. CI/CD автоматизация
18. Mypy strict + Pylance
19. Sentry monitoring
20. ASO планирование

---

## Файлы где детали

- **`TECH_DEBT.md`** в этом репо (backend) — 1100+ строк, полная история
- **`aima-app/TECH_DEBT.md`** — Flutter-specific
- **`aima-app/APP_STORE_FORM_FIELDS.md`** — что вставлять в App Store Connect
- **`aima-app/APPLE_IAP_SETUP.md`** — как настроить Apple IAP в App Store Connect
