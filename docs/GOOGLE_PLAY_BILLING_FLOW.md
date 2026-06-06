# Google Play Billing — как работает (полный флоу)

> Для AIMA (`kz.aima.aima`). Подписка: продукт **`kz.aima.aima.pro.monthly`**,
> 4 990 ₸/мес, авто-продление. Путь используется **только** когда приложение
> установлено из Google Play (иначе — FreedomPay).

---

## Действующие лица

- **Пользователь** — платит со своего Google-аккаунта (привязанная карта)
- **Приложение** (Flutter, плагин `in_app_purchase`)
- **Google Play** — проводит оплату, держит деньги, берёт комиссию
- **Backend** (FastAPI) — проверяет покупку, активирует PRO
- **Google Play Developer API** — backend спрашивает у Google «покупка настоящая?»
- **Keycloak** — хранит `plan=PRO` пользователя

---

## Флоу покупки (пошагово)

```
┌──────────┐      ┌─────────────┐      ┌──────────────┐      ┌──────────┐      ┌──────────┐
│  Юзер    │      │ Приложение  │      │  Google Play │      │ Backend  │      │ Keycloak │
└────┬─────┘      └──────┬──────┘      └──────┬───────┘      └────┬─────┘      └────┬─────┘
     │                   │                    │                   │                 │
     │ 1. жмёт           │                    │                   │                 │
     │  «Оформить» ─────►│                    │                   │                 │
     │                   │ 2. запускает       │                   │                 │
     │                   │  окно покупки ────►│                   │                 │
     │                   │  (product id)      │                   │                 │
     │                   │                    │                   │                 │
     │ 3. подтверждает оплату в окне Google   │                   │                 │
     │◄──────────────────┼───── окно Google ─┤                   │                 │
     │  (отпечаток/PIN,   │                    │                   │                 │
     │   карта Google)    │                    │                   │                 │
     │                   │                    │                   │                 │
     │                   │ 4. Google списал,  │                   │                 │
     │                   │◄─ вернул purchase ─┤                   │                 │
     │                   │   token            │                   │                 │
     │                   │                    │                   │                 │
     │                   │ 5. шлёт токен ─────┼──────────────────►│                 │
     │                   │  POST /payments/android/verify         │                 │
     │                   │                    │                   │                 │
     │                   │                    │ 6. backend спрашивает Google:        │
     │                   │                    │◄─ «токен валиден?» ┤                 │
     │                   │                    │  (Developer API,   │                 │
     │                   │                    │   service account) │                 │
     │                   │                    │ ─ «да, оплачено» ─►│                 │
     │                   │                    │                   │                 │
     │                   │                    │                   │ 7. активирует    │
     │                   │                    │                   │  plan=PRO ──────►│
     │                   │                    │                   │  subscription_end│
     │                   │                    │                   │                 │
     │                   │ 8. ◄─── «PRO активен» ──────────────── ┤                 │
     │◄── PRO в профиле ─┤                    │                   │                 │
     │                   │ 9. complete()      │                   │                 │
     │                   │  покупки в Google  │                   │                 │
```

### Что на каждом шаге

| # | Что происходит | Где в коде |
|---|---|---|
| 1 | Юзер жмёт кнопку подписки | `AndroidPurchaseButton` (app) |
| 2 | Приложение открывает окно Google | `IAPService.startPurchase()` → `in_app_purchase` |
| 3-4 | Google проводит оплату, отдаёт **purchase token** | плагин `in_app_purchase` |
| 5 | Приложение шлёт токен на backend | `POST /payments/android/verify` |
| 6 | Backend проверяет токен у Google | Google Play Developer API + сервис-аккаунт `google-play-billing@aima-prod-67f9d…` |
| 7 | Backend активирует подписку | `subscriptions` в БД + Keycloak `plan=PRO` |
| 8 | Профиль показывает «Подписка Month активна» | UserDTO (plan из Keycloak) |
| 9 | Приложение подтверждает покупку Google | `IAPService.complete()` — иначе Google повторит транзакцию |

---

## Ключевой момент: **деньги держит Google, не мы**

```
Юзер платит ──► Google Play (собирает деньги)
                    │
                    ├─ удерживает комиссию (15% для подписок 1-й год, далее по правилам)
                    │
                    └─ остаток ──► выплата на банковский счёт разработчика (раз в месяц)

Наш backend НЕ трогает деньги — он только ПРОВЕРЯЕТ покупку и включает PRO.
```

Поэтому «где деньги» = **в Google** (см. отдельный раздел ниже / Play Console → Financial reports).

---

## Авто-продление

- Подписка **сама продлевается** каждый месяц (Google списывает с карты юзера).
- При каждом продлении Google уведомляет (Real-time Developer Notifications, если настроены) ИЛИ backend проверяет статус токена.
- Backend продлевает `subscription_end` в Keycloak.

## Отмена / возврат

- Юзер отменяет подписку **в Google Play** (Подписки → AIMA → Отменить) — не в приложении.
- Подписка остаётся активной до конца оплаченного периода, потом не продлевается.
- Возвраты — через Google Play Console (Order management) или Google сам по своим правилам.

---

## Что нужно, чтобы это работало (чек-лист конфигурации)

- [x] Продукт `kz.aima.aima.pro.monthly` создан в Play Console (Active)
- [x] Сервис-аккаунт `google-play-billing@aima-prod-67f9d` + ключ в Railway (`GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`)
- [x] Google Play Android Developer API включён
- [x] Backend `POST /payments/android/verify` задеплоен
- [x] Приложение из Play → `InstallerSource.isGooglePlay == true` → Google Billing
- [ ] (опц.) Real-time Developer Notifications (Pub/Sub) для мгновенного уведомления о продлениях/отменах

---

## TL;DR

Юзер платит **через Google** (не через нас). Приложение получает «токен покупки», backend **проверяет его у Google** и включает PRO. **Деньги лежат у Google** и выплачиваются на банковский счёт раз в месяц за вычетом комиссии. Наш сервер только подтверждает покупку и активирует подписку.
