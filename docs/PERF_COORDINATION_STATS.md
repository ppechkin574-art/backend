# Perf coordination — statistics & client caching (2026-06-06)

Note from the iOS/client side after a client-perf pass. Heads-up + one backend
action item, to avoid duplicating the perf work already in flight on `main`
(gzip, RUM endpoint, ENT-options N+1 fix — 👍).

## What the CLIENT now does (app repo, branch `perf/cache-then-network`)
Cache-then-network (stale-while-revalidate, ObjectBox) on the high-traffic read
screens: **profile, global-statistics, leaderboard, home subjects, home
training-progress**. Plus launch prefetch (Profile + Statistics warmed after a
2s delay) and **HTTP/2** (dio_http2_adapter, backend ALPN h2 confirmed).

**Client contract / ask:** the client caches each response by serialising the
existing response models (`toJson`/`fromJson`). So:
- Please keep the **response shapes stable** for `/auth/profile`,
  `/user/statistics/global`, the leaderboard endpoints, `/user/daily-tests/
  subjects`, `/user/progress/trainers/summary`. Additive fields are fine.
- A breaking field change won't crash (a stale cache that fails to decode just
  falls back to the network), but please flag breaking changes so we bump a
  cache version.
- Because the client now caches these, **server-side caching of the same
  payloads is lower priority** — the win there is mostly the cold first hit.

## What I shipped on the BACKEND (already deployed)
Migration **`d7e8f9a0b1c2_stats_global_indexes`** — 7 composite/FK indexes
matching the `/user/statistics/global` hot paths (the answer-detail tables had
NO FK index, so each per-attempt join scanned the full table):
- `ent_attempts (student_guid, exam_type, completed_at)` + `(student_guid, status, completed_at)`
- `ent_attempt_answers (ent_attempt_id)`
- `trainer_attempts (student_guid, status, completed_at)`
- `trainer_attempt_questions (trainer_attempt_id)`, `trainer_attempt_answers (trainer_attempt_question_id)`
- `daily_test_attempts (student_guid, status, completed_at)`

Indexes only — no query/DTO/logic change. Tables are small today (ent_attempts
~364 rows), so plain `CREATE INDEX` was instant; if these grow large, switch to
`CREATE INDEX CONCURRENTLY` for future similar migrations.

## ⛏️ Backend action item — the real win: N+1 in `get_enhanced_global_statistic`
`src/quiz/services/statistic.py::get_enhanced_global_statistic` runs ~16
sequential queries, and the dominant cost (≈3s of the measured ~3.8s client
TTFB, indexes notwithstanding) is a **per-attempt fan-out**:
1. `_get_period_ent_statistic` / `_get_overall_ent_statistic` loop over
   completed attempts and call `get_attempt_statistic(attempt.id)` **per
   attempt** (each = `session.get` + ~5 sub-SELECTs) **plus**
   `get_attempt_answers_with_questions(attempt.id)` per attempt → ~6N+ queries.
2. `_calculate_ent_spend_time` re-fetches the same period attempts +
   `get_attempt_statistic` again (redundant with the period helper).
3. ENT period attempts are fetched 3× per exam_type (stats / completed-dates /
   spend-time); trainer 2×; daily 2–3× — same `(student_guid, period)` query
   repeated.
4. `get_overall_subject_progress` + `get_overall_topic_progress` (trainer) run
   two near-identical 5-table joins back-to-back.

**Suggested fix:** collapse the per-attempt loop into a few set-based
aggregations (GROUP BY), and fetch each `(student_guid, period)` slice once and
reuse. The indexes above make whatever queries remain cheap.

> ✅ **PARTLY SHIPPED (2026-06-06/07).** The *redundant-passes* half is done &
> deployed (commit on `main`): `get_enhanced_global_statistic` no longer
> re-fetches the period attempts or re-runs the per-attempt `get_attempt_statistic`
> loop for spend-time/dates — those are now computed once in the period helpers
> and reused (removed 8 redundant fetches + 3 redundant loops). Verified on prod:
> old-vs-new diff = 0 mismatches across all 40 students × 2 periods; post-deploy
> smoke PASS.
>
> ⏳ **STILL OPEN (owner's call):** the *core* per-attempt fan-out — looping
> `get_attempt_statistic(attempt.id)` (≈5 sub-queries each) + `get_attempt_
> answers_with_questions` per attempt in `_get_period_ent_statistic` /
> `_get_overall_ent_statistic`. Collapsing that to set-based GROUP-BY aggregates
> is the remaining win; left untouched (risky on the calc — full_exam Python
> question-id parsing + the multi-variant correctness CASE). NOTE the endpoint is
> `@cached(USER, ttl=3600)`, so this only runs on a cache miss (~1×/h/user).

## RUM
Saw `feat(analytics): RUM API-timing aggregation endpoint` on `main` — good, did
NOT build a parallel RUM. The client currently only has a debug-only timing log
(`[cachethennet] <label> netMs=…`, debugPrint, no-op in release) as a local
stopgap. When the RUM client SDK/contract is ready, point me at it and I'll wire
`time-to-first-paint` + `cache-hit` from the cache-then-network layer.
