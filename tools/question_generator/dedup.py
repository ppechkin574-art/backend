"""Near-duplicate detection against existing subject questions.

PURE similarity fn (`similarity`, `best_match`) is unit-tested — no network.
The orchestrating `flag_duplicates` fetches existing question text via the
admin API (best-effort) and annotates each draft's `validation` with a
dedup note (never drops — the human reviewer decides).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_DEDUP_THRESHOLD, get_logger

logger = get_logger("qgen.dedup")


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    """Return difflib ratio in [0,1] of two normalized strings. Pure."""
    na, nb = normalize(a), normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def best_match(
    candidate: str,
    existing: List[Tuple[Optional[int], str]],
) -> Tuple[float, Optional[int], Optional[str]]:
    """Find the closest existing question to `candidate`. Pure.

    Args:
        candidate: the draft's question text.
        existing: list of (question_id, question_text).

    Returns:
        (best_ratio, best_id, best_text). (0.0, None, None) when empty.
    """
    best_ratio = 0.0
    best_id: Optional[int] = None
    best_text: Optional[str] = None
    for qid, qtext in existing:
        ratio = similarity(candidate, qtext)
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = qid
            best_text = qtext
    return best_ratio, best_id, best_text


def draft_question_text(draft: Dict) -> str:
    """Concatenate a draft's text blocks into one comparable string."""
    parts: List[str] = []
    for block in draft.get("blocks", []) or []:
        if isinstance(block, dict) and block.get("type", "text") == "text":
            val = block.get("value")
            if val:
                parts.append(str(val))
    return " ".join(parts)


def flag_duplicates(
    drafts: List[Dict],
    existing: List[Tuple[Optional[int], str]],
    threshold: float = DEFAULT_DEDUP_THRESHOLD,
) -> int:
    """Annotate near-duplicate drafts in place. Returns count flagged.

    Never removes a draft. Adds to draft['validation']:
      - dedup_max_ratio
      - dedup_note         (only when >= threshold)
    and sets top-level draft['dedup_of_question_id'] when an id is known.
    """
    if not existing:
        logger.info("No existing questions to dedup against; skipping.")
        return 0

    flagged = 0
    for draft in drafts:
        cand = draft_question_text(draft)
        if not cand:
            continue
        ratio, qid, _qtext = best_match(cand, existing)
        validation = draft.setdefault("validation", {}) or {}
        if not isinstance(validation, dict):
            validation = {}
        validation["dedup_max_ratio"] = round(ratio, 3)
        if ratio >= threshold:
            flagged += 1
            note = (
                f"Возможный дубликат (similarity={ratio:.2f}"
                + (f", question_id={qid}" if qid is not None else "")
                + ")."
            )
            validation["dedup_note"] = note
            if qid is not None:
                draft["dedup_of_question_id"] = qid
        draft["validation"] = validation
    logger.info(
        "Dedup: flagged %d/%d drafts (threshold=%.2f).",
        flagged,
        len(drafts),
        threshold,
    )
    return flagged
