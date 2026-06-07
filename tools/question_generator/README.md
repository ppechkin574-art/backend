# Aima ЕНТ Question Generator (standalone CLI)

Ingest a textbook chapter → generate ЕНТ multiple-choice questions with Claude
→ verify each one with a stricter second pass → (optionally) flag near-duplicates
→ POST the results as **drafts** to the backend `/admin/question-drafts` API for
human review and publishing.

This is a **portable, standalone** tool. It talks to the backend over HTTP and
**does not import the backend app or models**, so it can run on any machine with
Python 3.9+ and the deps in `requirements.txt`. It is intentionally kept out of
the backend's main `requirements.txt` to keep the production image lean.

---

## Pipeline

```
chapter file (.pdf / .txt / .md)
        │
        ▼
1. ingest    extract the PDF text layer (pypdf); auto-detect scanned pages and
             OCR them with Claude vision (PyMuPDF render → image → text + LaTeX)
        ▼
2. chunk     split into sections by headings + a max-size cap   (PURE, tested)
        ▼
3. fewshot   (best-effort) GET ~3 real questions for the subject to match style
        ▼
4. generate  per section → Claude (gen-model) → draft JSON, then normalize/
             validate into the exact backend shape                (norm PURE, tested)
        ▼
5. verify    per draft → Claude (verify-model) → {key_correct, key_unique,
             distractors_plausible, grounded, confidence, notes}; attach as
             `validation`; flag (never drop) low-confidence/ungrounded items
        ▼
6. dedup     (optional) GET existing subject questions → difflib similarity;
             near-dups get a note + `dedup_of_question_id`        (sim PURE, tested)
        ▼
7. store     POST each draft to /admin/question-drafts (Bearer admin token),
             or with --dry-run write everything to drafts_output.json
```

Every step is per-item `try/except` with clear logging — one bad section or
draft is logged and skipped, never aborting the batch. Nothing is silently
dropped without a flag.

---

## Install

```bash
pip install -r tools/question_generator/requirements.txt
```

Pure functions (chunking, dedup similarity, draft normalization) need none of
these deps — only the LLM/HTTP/PDF paths do.

---

## Environment variables

Read from the environment (optionally from a `.env` via `python-dotenv`):

| Var | Purpose | How to get it |
|-----|---------|---------------|
| `ANTHROPIC_API_KEY` | Auth for Claude (generation, verification, OCR) | [Anthropic Console](https://console.anthropic.com) → API Keys |
| `AIMA_ADMIN_TOKEN`  | Bearer token for `/admin/*` (admin role required) | An admin SPA access token, or self-serve via Railway + a temp Keycloak admin user (see backend ops notes) |
| `AIMA_API_URL`      | Backend base URL | e.g. `https://backend-production-f2a1.up.railway.app` |

In `--dry-run` mode only `ANTHROPIC_API_KEY` is required (no POST is made, and
few-shot/dedup are skipped if the admin token / URL are absent).

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AIMA_ADMIN_TOKEN=eyJ...
export AIMA_API_URL=https://backend-production-f2a1.up.railway.app
```

---

## Usage

```bash
# Dry run — generate + verify, write JSON, no POST (good first run):
python -m tools.question_generator \
  --book chapter.pdf \
  --subject "История Казахстана" \
  --chapter "Глава 5" \
  --count 3 \
  --dry-run

# Live — POST drafts to the backend:
python -m tools.question_generator \
  --book chapter.pdf --subject "История Казахстана" --chapter "Глава 5" --count 3
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--book PATH` | — (required) | Chapter file: `.pdf`, `.txt`, or `.md` |
| `--subject NAME` | — (required) | Subject name (stored as `subject_name`) |
| `--chapter LABEL` | — (required) | Chapter label (stored in `source.chapter`) |
| `--count N` | `3` | Questions to generate per section |
| `--lang` | `ru` | Output language |
| `--dry-run` | off | Write `drafts_output.json` instead of POSTing |
| `--out PATH` | `drafts_output.json` | Dry-run output file |
| `--max-pages N` | all | Cap PDF pages ingested |
| `--max-chunk-chars N` | `6000` | Soft cap on section size before sub-splitting |
| `--gen-model ID` | `claude-sonnet-4-6` | Generation model |
| `--verify-model ID` | `claude-opus-4-8` | Verification model |
| `--ocr-model ID` | `claude-opus-4-8` | Vision model for scanned pages |
| `--no-verify` | off | Skip the verification pass |
| `--no-dedup` | off | Skip dedup against existing questions |
| `--no-fewshot` | off | Skip fetching real questions for style |
| `--dedup-threshold R` | `0.85` | Similarity ratio to flag a near-duplicate |
| `--book-title T` | file name | Override `source.book` |
| `--verbose` | off | Debug logging |

---

## Models

- **Generation** — `claude-sonnet-4-6` (strong quality/cost for batch work).
- **Verification** — `claude-opus-4-8` (stricter, most-capable check pass).
- **OCR (scanned pages)** — `claude-opus-4-8` (best vision + formula→LaTeX).

All overridable via the flags above. Calls use adaptive thinking and stream the
response (avoids HTTP timeouts), with structured JSON output (`output_config.format`)
for reliable parsing.

---

## The exact draft shape POSTed

One JSON body per draft to `POST {AIMA_API_URL}/admin/question-drafts`
(`Authorization: Bearer {AIMA_ADMIN_TOKEN}`). Matches the backend
`QuestionDraftCreateDTO` (validated against the real DTO):

```jsonc
{
  "subject_name": "Биология",
  "topic_name": "Световая фаза",
  "difficulty": "easy|medium|hard",            // backend Difficulty enum
  "question_type": "single_choice|multiple_choice",  // backend QuestionType enum
  "blocks": [
    { "type": "text", "order": 0, "value": "Где протекает световая фаза?" }
  ],
  "variants": [                                  // flat "value"; multi-correct => multiple is_correct:true
    { "value": "В тилакоидах", "is_correct": true },
    { "value": "В строме",     "is_correct": false }
  ],
  "task_description_ru": null,
  "question_translation_ru": null,
  "explanation_ru": "По тексту: «...».",
  "source": { "book": "chapter.pdf", "chapter": "Глава 5", "page": null },
  "validation": {                                // filled by the verify (+dedup) step
    "verifier": "claude-opus-4-8",
    "confidence": 0.92,
    "key_correct": true,
    "key_unique": true,
    "distractors_plausible": true,
    "grounded": true,
    "groundedness": "grounded",
    "notes": "...",
    "needs_human": false,
    "dedup_max_ratio": 0.31                       // present when dedup ran
  },
  "dedup_of_question_id": null,                  // set when a near-dup is found
  "status": "draft"
}
```

Difficulty (`easy|medium|hard`) and question_type (`single_choice|multiple_choice`)
mirror `src/quiz/dtos/enums.py`; the body mirrors `src/quiz/dtos/question_drafts.py`.

---

## Review flow (drafts → admin → publish)

1. The tool POSTs everything as `status: "draft"`.
2. A reviewer opens the admin panel (`GET /admin/question-drafts?status=draft`),
   reads each item, and prioritises `validation.needs_human = true` ones.
3. Reviewer edits via `PATCH /admin/question-drafts/{id}` if needed.
4. `POST /admin/question-drafts/{id}/publish` materializes a live question;
   `POST /admin/question-drafts/{id}/reject` discards. Nothing reaches the live
   `questions` table without an explicit human publish.

---

## What's tested vs what needs the real key + chapter

**Unit-tested, runnable WITHOUT any API key or network** (`tests/test_pure.py`):

- `chunk.chunk_text` — heading detection (markdown / «Глава N» / ALL-CAPS),
  size-based sub-splitting, min-length noise floor.
- `dedup.similarity` / `best_match` / `flag_duplicates` — normalization, ratio
  bounds, closest-match selection, in-place flagging + `dedup_of_question_id`.
- `draft_schema.normalize_draft` / `normalize_many` — enum coercion (RU aliases),
  single↔multiple reconciliation by correct-count, block re-ordering, variant
  flattening, and rejection of structurally bad drafts (no blocks / <2 variants /
  no correct answer).
- `llm.extract_json` — JSON extraction from plain / fenced / prose-wrapped output.

Run them:

```bash
python3 tools/question_generator/tests/test_pure.py     # plain runner, no deps
# or
pytest tools/question_generator/tests/test_pure.py
```

Also exercised locally without the API: `ingest` on a `.txt` sample → `chunk`
(3 sections), and the `--dry-run` store path producing a JSON payload that
**validates against the real backend `QuestionDraftCreateDTO`**.

**Needs the real `ANTHROPIC_API_KEY` + a chapter file to validate end-to-end:**

- generation (`generate.py`), verification (`verify.py`), and scanned-page OCR
  (`ingest.py` vision path) — these make live Claude calls.
- few-shot fetch and dedup fetch — these need `AIMA_ADMIN_TOKEN` + `AIMA_API_URL`
  (both best-effort; the tool degrades gracefully without them).

### Two blockers to a full live run

1. **`ANTHROPIC_API_KEY`** — not available in this environment.
2. **A real chapter file** (and, for POST mode, a valid **admin token**) — not
   available here.

Once both are present, the recommended first run is `--dry-run` to inspect
`drafts_output.json` before POSTing.

---

## Cost note

Per question you pay roughly: one share of a section-level generation call
(Sonnet 4.6, $3/$15 per 1M in/out) plus one verification call (Opus 4.8,
$5/$25 per 1M in/out), plus a one-time OCR cost per scanned page (Opus 4.8
vision). For a typical chapter of a few dozen sections this is on the order of a
few dollars. Levers: lower `--count`, use `--no-verify` for a cheaper first
pass, switch `--verify-model` to `claude-sonnet-4-6`, or cap pages with
`--max-pages`. Always start with `--dry-run` so you don't pay for POSTs you
won't keep.
```
