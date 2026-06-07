"""Normalize + validate a model-produced draft dict into the exact shape the
backend QuestionDraftCreateDTO accepts.

PURE (no network) — unit-tested. The model is asked to emit JSON close to the
target shape, but we never trust it blindly: we coerce enum values, fix block
ordering, ensure flat variant `value`s, and sanity-check correctness counts.

Backend DTO recap (src/quiz/dtos/question_drafts.py):
  QuestionDraftCreateDTO:
    subject_name: str|None, topic_name: str|None,
    difficulty: Difficulty|None (easy|medium|hard),
    question_type: QuestionType (single_choice|multiple_choice),
    blocks: [{type, order, value}],
    variants: [{value, is_correct}],
    task_description_ru, question_translation_ru, explanation_ru,
    source: {book, chapter, page}, validation: dict, dedup_of_question_id: int
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import BLOCK_TYPES, DIFFICULTIES, QUESTION_TYPES


class DraftValidationError(ValueError):
    """Raised when a draft cannot be coerced into a valid create payload."""


def _coerce_difficulty(value: Any) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower()
    aliases = {
        "easy": "easy", "лёгкий": "easy", "легкий": "easy", "1": "easy",
        "medium": "medium", "средний": "medium", "2": "medium",
        "hard": "hard", "трудный": "hard", "сложный": "hard", "3": "hard",
    }
    v = aliases.get(v, v)
    if v not in DIFFICULTIES:
        return None  # unknown -> let backend default it (Difficulty|None)
    return v


def _coerce_question_type(value: Any, n_correct: int) -> str:
    if value is not None:
        v = str(value).strip().lower()
        aliases = {
            "single_choice": "single_choice", "single": "single_choice",
            "one": "single_choice", "single-choice": "single_choice",
            "multiple_choice": "multiple_choice", "multiple": "multiple_choice",
            "multi": "multiple_choice", "multiple-choice": "multiple_choice",
        }
        v = aliases.get(v, v)
        if v in QUESTION_TYPES:
            # Reconcile with actual correct count to avoid contradictions.
            if v == "single_choice" and n_correct > 1:
                return "multiple_choice"
            return v
    # Infer from number of correct answers.
    return "multiple_choice" if n_correct > 1 else "single_choice"


def _coerce_blocks(raw_blocks: Any, fallback_text: Any = None) -> List[Dict]:
    blocks: List[Dict] = []
    if isinstance(raw_blocks, list):
        for i, b in enumerate(raw_blocks):
            if isinstance(b, dict):
                btype = str(b.get("type", "text")).strip().lower()
                if btype not in BLOCK_TYPES:
                    btype = "text"
                value = b.get("value")
                if value is None:
                    continue
                blocks.append(
                    {"type": btype, "order": i, "value": str(value)}
                )
            elif isinstance(b, str) and b.strip():
                blocks.append({"type": "text", "order": i, "value": b})
    if not blocks and fallback_text:
        blocks = [{"type": "text", "order": 0, "value": str(fallback_text)}]
    # Re-sequence order to be contiguous from 0.
    for i, b in enumerate(blocks):
        b["order"] = i
    return blocks


def _coerce_variants(raw_variants: Any) -> Tuple[List[Dict], int]:
    variants: List[Dict] = []
    n_correct = 0
    if isinstance(raw_variants, list):
        for v in raw_variants:
            if not isinstance(v, dict):
                # Bare string option -> not correct by default.
                if isinstance(v, str) and v.strip():
                    variants.append({"value": v.strip(), "is_correct": False})
                continue
            value = v.get("value")
            if value is None and isinstance(v.get("text"), str):
                value = v.get("text")
            if value is None:
                # Some models nest in blocks; flatten the first text block.
                blocks = v.get("blocks")
                if isinstance(blocks, list):
                    for bb in blocks:
                        if isinstance(bb, dict) and bb.get("value"):
                            value = bb["value"]
                            break
            if value is None:
                continue
            is_correct = bool(v.get("is_correct", False))
            if is_correct:
                n_correct += 1
            variants.append({"value": str(value), "is_correct": is_correct})
    return variants, n_correct


def normalize_draft(
    raw: Dict[str, Any],
    subject_name: str,
    source: Optional[Dict[str, Any]] = None,
    lang: str = "ru",
) -> Dict[str, Any]:
    """Coerce one raw model dict into a backend-ready draft dict.

    The model returns language-neutral fields (task_description, explanation,
    question_translation); we route them into the backend's _ru or _kk columns
    based on `lang` so a Kazakh textbook fills the Kazakh fields. Falls back to
    legacy _ru/_kk-suffixed keys if the model used them.

    Raises DraftValidationError if the draft is structurally unusable
    (no question blocks, fewer than 2 options, or zero correct answers).
    """
    if not isinstance(raw, dict):
        raise DraftValidationError("draft is not an object")

    blocks = _coerce_blocks(raw.get("blocks"), fallback_text=raw.get("question"))
    if not blocks:
        raise DraftValidationError("draft has no question text blocks")

    variants, n_correct = _coerce_variants(raw.get("variants"))
    if len(variants) < 2:
        raise DraftValidationError(
            f"draft needs >=2 variants, got {len(variants)}"
        )
    if n_correct < 1:
        raise DraftValidationError("draft has no correct variant")

    qtype = _coerce_question_type(raw.get("question_type"), n_correct)
    difficulty = _coerce_difficulty(raw.get("difficulty"))

    sfx = "kk" if (lang or "ru").lower() == "kk" else "ru"
    task = raw.get("task_description") or raw.get(f"task_description_{sfx}") or None
    trans = raw.get("question_translation") or raw.get(f"question_translation_{sfx}") or None
    expl = raw.get("explanation") or raw.get(f"explanation_{sfx}") or None

    draft: Dict[str, Any] = {
        "subject_name": subject_name,
        "topic_name": (raw.get("topic_name") or None),
        "difficulty": difficulty,
        "question_type": qtype,
        "blocks": blocks,
        "variants": variants,
        f"task_description_{sfx}": task,
        f"question_translation_{sfx}": trans,
        f"explanation_{sfx}": expl,
        "source": source or raw.get("source") or None,
        # validation filled by verify step; carry through if present.
        "validation": raw.get("validation") if isinstance(raw.get("validation"), dict) else None,
        "status": "draft",
    }
    return draft


def normalize_many(
    raws: List[Dict[str, Any]],
    subject_name: str,
    source: Optional[Dict[str, Any]] = None,
    lang: str = "ru",
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalize a list; collect per-item errors instead of aborting.

    Returns (ok_drafts, error_messages).
    """
    ok: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, raw in enumerate(raws):
        try:
            ok.append(normalize_draft(raw, subject_name, source, lang=lang))
        except DraftValidationError as e:
            errors.append(f"draft #{i}: {e}")
    return ok, errors
