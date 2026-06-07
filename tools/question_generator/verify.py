"""Verification step: a second Claude pass per draft.

Attaches a `validation` dict to each draft. NEVER drops — low-confidence
drafts are flagged so the human reviewer decides. Per-item try/except so one
bad call doesn't sink the batch.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .config import DEFAULT_VERIFY_MODEL, get_logger
from .llm import call_json
from .prompts import VERIFICATION_SCHEMA, VERIFICATION_SYSTEM, build_verification_prompt

logger = get_logger("qgen.verify")

# Drafts with confidence below this get an explicit low-confidence flag note.
LOW_CONFIDENCE = 0.6


def verify_draft(
    client,
    model: str,
    section_text: str,
    draft: Dict,
) -> Dict:
    """Return a validation dict for one draft (or an error-marked one)."""
    user = build_verification_prompt(section_text, draft)
    try:
        result = call_json(
            client=client,
            model=model,
            system=VERIFICATION_SYSTEM,
            user=user,
            schema=VERIFICATION_SCHEMA,
            max_tokens=4000,
        )
    except Exception as e:  # pragma: no cover - network path
        logger.warning("Verify call failed: %s", e)
        return {
            "verifier": model,
            "confidence": 0.0,
            "groundedness": "unknown",
            "error": str(e),
            "needs_human": True,
        }

    confidence = float(result.get("confidence", 0.0) or 0.0)
    grounded = bool(result.get("grounded", False))
    validation = {
        "verifier": model,
        "confidence": round(confidence, 3),
        "key_correct": bool(result.get("key_correct", False)),
        "key_unique": bool(result.get("key_unique", False)),
        "distractors_plausible": bool(result.get("distractors_plausible", False)),
        "grounded": grounded,
        "groundedness": "grounded" if grounded else "ungrounded",
        "notes": result.get("notes", ""),
        "needs_human": (confidence < LOW_CONFIDENCE)
        or (not grounded)
        or (not result.get("key_correct", False)),
    }
    return validation


def verify_drafts(
    client,
    drafts_with_sections: List[Dict],
    model: str = DEFAULT_VERIFY_MODEL,
) -> int:
    """Verify a batch in place.

    Args:
        drafts_with_sections: list of {"draft": dict, "section_text": str}.
        model: verifier model id.

    Returns:
        Number of drafts flagged needs_human.
    """
    flagged = 0
    for i, pair in enumerate(drafts_with_sections):
        draft = pair["draft"]
        section_text = pair.get("section_text", "")
        validation = verify_draft(client, model, section_text, draft)
        # Merge with any pre-existing validation (e.g. dedup runs later/earlier).
        existing = draft.get("validation")
        if isinstance(existing, dict):
            existing.update(validation)
            draft["validation"] = existing
        else:
            draft["validation"] = validation
        if validation.get("needs_human"):
            flagged += 1
        logger.info(
            "Verified draft %d/%d: confidence=%.2f needs_human=%s",
            i + 1,
            len(drafts_with_sections),
            validation.get("confidence", 0.0),
            validation.get("needs_human"),
        )
    logger.info("Verification: %d/%d flagged for human review.", flagged, len(drafts_with_sections))
    return flagged
