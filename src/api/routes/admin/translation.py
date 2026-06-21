"""Admin endpoints for the Kazakh question-translation workflow.

The translator is a Claude Code session (no in-backend LLM). Flow:
  1. GET  /admin/translation/export  → a self-describing JSON of untranslated
     questions (+ glossary + saved params + a `how` instruction).
  2. operator hands the file to Claude → gets a translated file back.
  3. POST /admin/translation/import  → applies *_kk fields + sets status.

Plus coverage, glossary CRUD and per-subject config, so the operator drives it
all from the admin panel without tokens or DB access.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from api.dependencies import allow_only_admins, get_db_session
from app_config.models import AppSetting
from quiz.dtos.enums import BlockType
from quiz.models.edu_content import Hint, Question, Subject, Variant
from quiz.models.text_blocks import TextBlockLink
from translation.models import TranslationConfig, TranslationGlossary

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/translation",
    tags=["admin"],
    dependencies=[Depends(allow_only_admins)],
)

_STATUSES = {"none", "queued", "draft", "done"}

_HOW = (
    "Переведи каждый вопрос с русского на казахский. Поля для перевода: "
    "question_text, каждый variant.text, hint, task_description, explanation. "
    "Тон и длину бери из meta (tone/length). Используй meta.glossary для замен "
    "терминов. Формулы/LaTeX (r\"...\") и числа НЕ меняй. Верни JSON вида "
    "{\"questions\":[{\"id\":N,\"question_text_kk\":\"…\",\"variants\":"
    "[{\"id\":N,\"text_kk\":\"…\"}],\"hint_kk\":\"…\",\"task_description_kk\":\"…\","
    "\"explanation_kk\":\"…\"}]} — те же id. Пустые исходные поля пропусти."
)


# ─────────────────────────── helpers ───────────────────────────


def _blocks_text(link: TextBlockLink | None) -> str:
    """Concatenate the text-type blocks of a link into one RU string (the
    translatable surface). Media blocks (image/video) are skipped — they don't
    translate and the kk text replaces the lead text block on the client."""
    if link is None or not link.blocks:
        return ""
    parts = [
        b.value
        for b in sorted(link.blocks, key=lambda b: (b.order if b.order is not None else 0))
        if b.type == BlockType.text and b.value
    ]
    return "\n".join(p.strip() for p in parts).strip()


def _pick_sample(ids: list[int], sample: int, limit: int) -> list[int]:
    """Every `sample`-th id (1 = all), capped at `limit` (hard max 200)."""
    return ids[:: max(1, sample)][: min(200, max(1, limit))]


_PAUSE_KEY = "translation_paused"


def _is_paused(session: Session) -> bool:
    """Background-worker pause flag. Absent row → paused by default, so the
    operator must press «Продолжить» to start translating (explicit control)."""
    row = session.query(AppSetting).filter(AppSetting.key == _PAUSE_KEY).first()
    return True if row is None else row.value == "1"


def _set_paused(session: Session, paused: bool) -> None:
    val = "1" if paused else "0"
    row = session.query(AppSetting).filter(AppSetting.key == _PAUSE_KEY).first()
    if row is None:
        session.add(
            AppSetting(key=_PAUSE_KEY, value=val, description="Пауза фонового переводчика (1=пауза)")
        )
    else:
        row.value = val
    session.commit()


# ─────────────────────────── coverage ───────────────────────────


@router.get("/coverage")
def coverage(session: Session = Depends(get_db_session)):
    """Per-subject translation progress: none / draft / done / total."""
    rows = (
        session.query(
            Subject.id,
            Subject.name,
            Question.translation_status_kk,
            func.count(Question.id),
        )
        .outerjoin(Question, Question.subject_id == Subject.id)
        .group_by(Subject.id, Subject.name, Question.translation_status_kk)
        .all()
    )
    agg: dict[int, dict] = {}
    for sid, sname, status, cnt in rows:
        d = agg.setdefault(
            sid,
            {
                "subject_id": sid,
                "subject_name": sname,
                "none": 0,
                "queued": 0,
                "draft": 0,
                "done": 0,
                "total": 0,
            },
        )
        if status in _STATUSES:
            d[status] += cnt
            d["total"] += cnt
    items = sorted(agg.values(), key=lambda x: x["subject_name"] or "")
    return {"items": items}


# ─────────────────────────── queue ───────────────────────────


@router.post("/queue")
def queue_subject(subject_id: int, session: Session = Depends(get_db_session)):
    """Operator clicks «Перевести» — flag this subject's untranslated questions
    as 'queued' so the background translation worker (a scheduled Claude job)
    picks them up. Returns how many were queued."""
    n = (
        session.query(Question)
        .filter(
            Question.subject_id == subject_id,
            Question.translation_status_kk == "none",
        )
        .update(
            {Question.translation_status_kk: "queued"}, synchronize_session=False
        )
    )
    session.commit()
    return {"queued": n}


@router.post("/requeue")
def requeue_question(question_id: int, session: Session = Depends(get_db_session)):
    """Operator «Перевести заново» — put one already-translated question back into
    the queue so the worker re-translates it (its kk fields get overwritten)."""
    q = session.query(Question).filter(Question.id == question_id).first()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    q.translation_status_kk = "queued"
    session.commit()
    return {"ok": True, "question_id": question_id, "status": "queued"}


@router.get("/control")
def get_control(session: Session = Depends(get_db_session)):
    """Pause state of the background translator — read by the admin UI (to pick
    «Продолжить» vs «Идёт перевод…») and by the worker (skip while paused)."""
    return {"paused": _is_paused(session)}


@router.post("/control/resume")
def resume_translation(session: Session = Depends(get_db_session)):
    """Operator «Продолжить» — let the worker process the queue."""
    _set_paused(session, False)
    return {"paused": False}


@router.post("/control/cancel")
def cancel_translation(session: Session = Depends(get_db_session)):
    """Operator «Отменить» — drop everything still queued back to 'none' and
    pause. Already-translated questions keep their kk."""
    n = (
        session.query(Question)
        .filter(Question.translation_status_kk == "queued")
        .update({Question.translation_status_kk: "none"}, synchronize_session=False)
    )
    session.commit()
    _set_paused(session, True)
    return {"cleared": n, "paused": True}


@router.get("/queued-subjects")
def queued_subjects(session: Session = Depends(get_db_session)):
    """Subjects with questions waiting for translation — polled by the worker."""
    rows = (
        session.query(Subject.id, Subject.name, func.count(Question.id))
        .join(Question, Question.subject_id == Subject.id)
        .filter(Question.translation_status_kk == "queued")
        .group_by(Subject.id, Subject.name)
        .all()
    )
    return [
        {"subject_id": sid, "subject_name": name, "queued": cnt}
        for sid, name, cnt in rows
    ]


# ─────────────────────────── export ───────────────────────────


@router.get("/export")
def export_for_translation(
    subject_id: int,
    status: str = "none",
    limit: int = 200,
    session: Session = Depends(get_db_session),
):
    """Build the self-describing translation file for one subject.

    `status`: which questions to ship — none (default) / draft / done / all.
    """
    subject = session.query(Subject).filter(Subject.id == subject_id).first()
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    q = (
        session.query(Question)
        .options(
            selectinload(Question.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.variants).selectinload(Variant.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.hint).selectinload(Hint.link).selectinload(TextBlockLink.blocks),
        )
        .filter(Question.subject_id == subject_id)
    )
    if status != "all":
        if status not in _STATUSES:
            raise HTTPException(status_code=400, detail="bad status")
        q = q.filter(Question.translation_status_kk == status)
    questions = q.order_by(Question.id).limit(min(1000, max(1, limit))).all()

    cfg = (
        session.query(TranslationConfig)
        .filter(TranslationConfig.subject_id == subject_id)
        .first()
    )
    glossary = (
        session.query(TranslationGlossary)
        .filter(
            (TranslationGlossary.subject_id == subject_id)
            | (TranslationGlossary.subject_id.is_(None))
        )
        .all()
    )

    out_questions = []
    for ques in questions:
        out_questions.append(
            {
                "id": ques.id,
                "question_text_ru": _blocks_text(ques.link),
                "variants": [
                    {"id": v.id, "text_ru": _blocks_text(v.link), "is_correct": v.is_correct}
                    for v in ques.variants
                ],
                "hint_ru": _blocks_text(ques.hint.link) if ques.hint else "",
                "task_description_ru": ques.task_description_ru or "",
                "explanation_ru": ques.explanation_ru or "",
            }
        )

    return {
        "meta": {
            "subject_id": subject_id,
            "subject": subject.name,
            "tone": cfg.tone if cfg else "official",
            "length": cfg.length if cfg else "keep",
            "instruction": (cfg.instruction if cfg else None),
            "glossary": [{"ru": g.term_ru, "kk": g.term_kk} for g in glossary],
            "count": len(out_questions),
            "how": _HOW,
        },
        "questions": out_questions,
    }


# ─────────────────────────── preview ───────────────────────────


@router.get("/preview")
def preview_translations(
    subject_id: int,
    status: str = "done",
    sample: int = 1,
    limit: int = 50,
    session: Session = Depends(get_db_session),
):
    """RU↔KK pairs of already-translated questions, for in-admin spot-checking.

    `sample`: take every Nth question by id (1 = all). `status`: done | draft.
    """
    if status not in {"done", "draft"}:
        raise HTTPException(status_code=400, detail="status must be done|draft")
    sample = max(1, sample)

    ids = [
        qid
        for (qid,) in session.query(Question.id)
        .filter(
            Question.subject_id == subject_id,
            Question.translation_status_kk == status,
        )
        .order_by(Question.id)
        .all()
    ]
    total = len(ids)
    picked = _pick_sample(ids, sample, limit)
    if not picked:
        return {"items": [], "total": total, "shown": 0, "sample": sample}

    questions = (
        session.query(Question)
        .options(
            selectinload(Question.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.variants).selectinload(Variant.link).selectinload(TextBlockLink.blocks),
            selectinload(Question.hint).selectinload(Hint.link).selectinload(TextBlockLink.blocks),
        )
        .filter(Question.id.in_(picked))
        .order_by(Question.id)
        .all()
    )

    items = []
    for q in questions:
        items.append(
            {
                "id": q.id,
                "question": {"ru": _blocks_text(q.link), "kk": q.question_text_kk or ""},
                "variants": [
                    {
                        "id": v.id,
                        "ru": _blocks_text(v.link),
                        "kk": v.variant_text_kk or "",
                        "is_correct": v.is_correct,
                    }
                    for v in q.variants
                ],
                "hint": {
                    "ru": _blocks_text(q.hint.link) if q.hint else "",
                    "kk": q.hint_text_kk or "",
                },
                "task_description": {
                    "ru": q.task_description_ru or "",
                    "kk": q.task_description_kk or "",
                },
                "explanation": {
                    "ru": q.explanation_ru or "",
                    "kk": q.explanation_kk or "",
                },
            }
        )

    return {"items": items, "total": total, "shown": len(items), "sample": sample}


# ─────────────────────────── import ───────────────────────────


class _ImportVariant(BaseModel):
    id: int
    text_kk: str | None = None


class _ImportItem(BaseModel):
    id: int
    question_text_kk: str | None = None
    variants: list[_ImportVariant] = []
    hint_kk: str | None = None
    task_description_kk: str | None = None
    explanation_kk: str | None = None
    question_translation_kk: str | None = None


class _ImportPayload(BaseModel):
    questions: list[_ImportItem]
    mark: str = "done"  # 'done' | 'draft'


@router.post("/import")
def import_translations(
    payload: _ImportPayload, session: Session = Depends(get_db_session)
):
    """Apply a translated file: write *_kk fields + set status."""
    if payload.mark not in {"done", "draft"}:
        raise HTTPException(status_code=400, detail="mark must be done|draft")

    applied = 0
    skipped: list[int] = []
    for item in payload.questions:
        ques = session.query(Question).filter(Question.id == item.id).first()
        if ques is None:
            skipped.append(item.id)
            continue
        if item.question_text_kk is not None:
            ques.question_text_kk = item.question_text_kk
        if item.hint_kk is not None:
            ques.hint_text_kk = item.hint_kk
        if item.task_description_kk is not None:
            ques.task_description_kk = item.task_description_kk
        if item.explanation_kk is not None:
            ques.explanation_kk = item.explanation_kk
        if item.question_translation_kk is not None:
            ques.question_translation_kk = item.question_translation_kk
        ques.translation_status_kk = payload.mark
        for v in item.variants:
            if v.text_kk is None:
                continue
            var = (
                session.query(Variant)
                .filter(Variant.id == v.id, Variant.question_id == ques.id)
                .first()
            )
            if var is not None:
                var.variant_text_kk = v.text_kk
        applied += 1
    session.commit()
    return {"applied": applied, "skipped": skipped}


# ─────────────────────── manual per-question edit ───────────────────────


@router.patch("/questions/{question_id}")
def edit_one(
    question_id: int,
    payload: _ImportItem,
    mark: str = "done",
    session: Session = Depends(get_db_session),
):
    """Manual correction of one question's kk translation from the admin."""
    return import_translations(
        _ImportPayload(questions=[payload.model_copy(update={"id": question_id})], mark=mark),
        session,
    )


# ─────────────────────────── glossary CRUD ───────────────────────────


class _GlossaryIn(BaseModel):
    subject_id: int | None = None
    term_ru: str
    term_kk: str
    note: str | None = None


@router.get("/glossary")
def list_glossary(
    subject_id: int | None = None, session: Session = Depends(get_db_session)
):
    q = session.query(TranslationGlossary)
    if subject_id is not None:
        q = q.filter(
            (TranslationGlossary.subject_id == subject_id)
            | (TranslationGlossary.subject_id.is_(None))
        )
    rows = q.order_by(TranslationGlossary.term_ru).all()
    return [
        {
            "id": g.id,
            "subject_id": g.subject_id,
            "term_ru": g.term_ru,
            "term_kk": g.term_kk,
            "note": g.note,
        }
        for g in rows
    ]


@router.post("/glossary")
def add_glossary(body: _GlossaryIn, session: Session = Depends(get_db_session)):
    existing = (
        session.query(TranslationGlossary)
        .filter(
            TranslationGlossary.subject_id == body.subject_id,
            TranslationGlossary.term_ru == body.term_ru,
        )
        .first()
    )
    if existing:
        existing.term_kk = body.term_kk
        existing.note = body.note
        g = existing
    else:
        g = TranslationGlossary(
            subject_id=body.subject_id,
            term_ru=body.term_ru,
            term_kk=body.term_kk,
            note=body.note,
        )
        session.add(g)
    session.commit()
    return {"id": g.id}


@router.delete("/glossary/{glossary_id}", status_code=204)
def delete_glossary(glossary_id: int, session: Session = Depends(get_db_session)):
    session.query(TranslationGlossary).filter(
        TranslationGlossary.id == glossary_id
    ).delete()
    session.commit()


# ─────────────────────────── config ───────────────────────────


class _ConfigIn(BaseModel):
    tone: str = "official"  # conversational | official
    length: str = "keep"  # short | keep
    instruction: str | None = None


@router.get("/config/{subject_id}")
def get_config(subject_id: int, session: Session = Depends(get_db_session)):
    cfg = (
        session.query(TranslationConfig)
        .filter(TranslationConfig.subject_id == subject_id)
        .first()
    )
    if cfg is None:
        return {"subject_id": subject_id, "tone": "official", "length": "keep", "instruction": None}
    return {
        "subject_id": cfg.subject_id,
        "tone": cfg.tone,
        "length": cfg.length,
        "instruction": cfg.instruction,
    }


@router.put("/config/{subject_id}")
def set_config(
    subject_id: int, body: _ConfigIn, session: Session = Depends(get_db_session)
):
    if body.tone not in {"conversational", "official"} or body.length not in {"short", "keep"}:
        raise HTTPException(status_code=400, detail="bad tone/length")
    cfg = (
        session.query(TranslationConfig)
        .filter(TranslationConfig.subject_id == subject_id)
        .first()
    )
    if cfg is None:
        cfg = TranslationConfig(subject_id=subject_id)
        session.add(cfg)
    cfg.tone = body.tone
    cfg.length = body.length
    cfg.instruction = body.instruction
    session.commit()
    return {"ok": True}
