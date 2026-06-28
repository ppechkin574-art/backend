# AIMA — Security & Anti-Fraud Architecture

> Документ описывает текущее состояние безопасности продукта, реализованный функционал, известные пробелы и технический долг.
> Обновляется при каждом изменении security-слоя.

---

## Статус реализации

### ✅ Реализовано и работает

| Функция | Описание | Файл |
|---|---|---|
| Fraud events logging | Запись подозрительных событий в `fraud_events` | `security/repository.py` |
| Risk score | Профиль риска 0–100 для каждого пользователя | `security/models.py` — `UserRiskProfile` |
| `repeated_attempt` detector | Попытка повторно получить очки за один экзамен | `quiz/services/ent_attempts.py` |
| `rapid_points_farm` detector | Полный экзамен завершён < 5 сек/вопрос | `quiz/services/ent_attempts.py` |
| Block user (Keycloak) | `block_user()` → `set_active(False)` в Keycloak | `security/service.py` |
| `require_not_restricted` | 403 для restricted/blocked пользователей на quiz-роутах | `api/dependencies.py` |
| Login alert push | FCM-уведомление при входе с нового устройства | `auth/login_alert_service.py` |
| Admin security dashboard | UI: события, профили риска, блокировка | `admin/src/pages/security/` |
| Mark event reviewed | Отметить событие как проверенное | `POST /admin/security/events/{id}/mark-reviewed` |

### ⚠️ Реализовано частично

| Функция | Проблема |
|---|---|
| Login alert push | `firebase__enabled=false` в проде → уведомления не отправляются |
| Login alert content | Не содержит информацию о городе/устройстве |
| `is_suspicious` в PointsAuditLog | Всегда `False` — логика детекта не реализована |
| Restrict user | Пишет в БД, но не вызывает Keycloak → пользователь продолжает входить |

---

## Технический долг

### 🔴 Высокий приоритет

#### TD-001 — device_id не передаётся глобально
- **Проблема:** `device_id` передаётся только в теле JSON на конкретных эндпоинтах (аналитика, тренировки). На auth/quiz эндпоинтах его нет.
- **Решение:** Добавить `X-Device-ID` header в Flutter Dio interceptor → принимать в backend middleware и прокидывать в fraud events.
- **Статус:** В работе

#### TD-002 — Keycloak Brute Force Protection ✅ ЗАКРЫТ
- **Статус:** Включён. Настройки: Mode=Lockout temporarily, Max failures=5, Wait increment=30s, Max wait=15min, Failure reset=12h.
- Данные о блокировках отображаются в admin → Security → User Detail → карточка «Keycloak — Brute Force Detection».

#### TD-003 — Login security events не логируются
- **Проблема:** При входе пользователя не создаётся запись в `fraud_events`. IP, user-agent и device не сохраняются в БД.
- **Решение:** В `auth/routes.py` → login endpoint добавить `fraud_events.log_event(event_type="login", ...)` с IP, city, device_id.
- **Статус:** В работе

### 🟡 Средний приоритет

#### TD-004 — Накрутка в тренажёре (N/A)
- **Статус:** **Не актуально.** Тренажёр не начисляет очки в лидерборд (операторское правило от 23.05.2026). Fraud risk = 0.

#### TD-005 — Answer pattern detection не реализован
- **Проблема:** Нет детекта: (a) пользователь всегда выбирает одну позицию ответа, (b) скорость ответов < 2 сек/вопрос.
- **Статус:** В работе

#### TD-006 — Keycloak события не отображаются в admin
- **Проблема:** Если Keycloak блокирует аккаунт за брутфорс, в нашем admin security dashboard это не видно.
- **Решение:** Добавить endpoint для запроса Keycloak attack-detection статуса пользователя.
- **Статус:** Запланировано

### 🟢 Низкий приоритет

#### TD-007 — Мультиаккаунты по IP/device_id
- Нет детекта нескольких аккаунтов с одного IP или device_id.
- **Статус:** Запланировано

#### TD-008 — PRO без валидного payment webhook
- Нет проверки что PRO статус был выдан только через валидный webhook от Apple/Google.
- **Статус:** Запланировано

---

## Политики безопасности (Admin Actions)

### Правила для администраторов

1. **Автоматическая блокировка** — только при `risk_score >= 90` И подтверждении одним из детекторов.
2. **Никогда не блокировать автоматически** при единственном событии — нужно минимум 2 разных детектора.
3. **Все действия администратора логируются** в `fraud_events` с `event_type="admin_action"`.
4. **False positive** — при снятии флага обязательно указать причину, risk_score сбрасывается до 0.
5. **Watchlist** — не блокирует пользователя, только увеличивает мониторинг.

### Admin Actions — разрешённые действия

| Действие | Условие | Обратимо |
|---|---|---|
| Add to watchlist | Любой risk_score > 30 | ✓ |
| Freeze leaderboard points | risk_score > 50 | ✓ |
| Disable referral rewards | risk_score > 50 | ✓ |
| Reset suspicious points | risk_score > 60 | ✓ |
| Temporary block (24h–7d) | risk_score > 70 | ✓ |
| Permanent block | risk_score > 90 + 2 детектора | ✗ |
| Mark as false positive | Любой | ✓ |
| Unblock | Только после ревью | ✓ |

---

## Risk Score — логика

| Score | Статус | Триггеры |
|---|---|---|
| 0–30 | `normal` | — |
| 31–60 | Watchlist candidate | 1 детектор сработал |
| 61–80 | `restricted` | 2+ детектора или критический 1 |
| 81–100 | `blocked` | Высокий score + подтверждение |

### Детекторы и веса

| Детектор | event_type | risk_score |
|---|---|---|
| Повторная отправка попытки | `repeated_attempt` | +75 |
| Слишком быстрый экзамен (<5с/вопрос) | `rapid_points_farm` | +85 |
| Вход с нового города | `suspicious_login` | +30 |
| Шаблонные ответы (>80% одна позиция) | `pattern_answers` | +60 |
| Скорость ответов < 2 сек | `bot_speed_answers` | +70 |
| Брутфорс (Keycloak) | `brute_force` | +80 |

---

## Конфигурация правил

> Все пороги планируется сделать конфигурируемыми через таблицу `fraud_rule_configs` (TD в разработке).

Текущие пороги (хардкод):

```python
RAPID_EXAM_SECONDS_PER_QUESTION = 5      # ent_attempts.py
BOT_ANSWER_SPEED_SECONDS = 2             # запланировано
PATTERN_ANSWER_THRESHOLD_PERCENT = 80   # запланировано
LOGIN_NEW_CITY_ALERT = True              # запланировано
```

---

*Последнее обновление: 2026-06-28*
