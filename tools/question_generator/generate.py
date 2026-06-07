"""Generation step: per-section Claude call -> normalized draft dicts.

Also (best-effort) fetches a few real questions for the subject from the admin
API to seed house style. Failures in few-shot fetch are non-fatal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import get_logger
from .draft_schema import normalize_many
from .llm import call_json
from .prompts import GENERATION_SCHEMA, GENERATION_SYSTEM, build_generation_prompt

logger = get_logger("qgen.generate")


def fetch_fewshot(
    api_url: str,
    admin_token: str,
    subject_name: str,
    count: int = 3,
    timeout: int = 30,
) -> List[Dict]:
    """Pull ~`count` existing questions for tone matching. Best-effort -> [].

    The admin questions endpoint shape can vary; we defensively walk common
    envelope keys and reduce each question to {blocks, variants} if possible.
    """
    try:
        import requests  # lazy

        resp = requests.get(
            api_url.rstrip("/") + "/admin/questions",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"limit": count, "search": subject_name},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.info("Few-shot fetch HTTP %s; skipping.", resp.status_code)
            return []
        data = resp.json()
        items = _items_from_envelope(data)
        examples: List[Dict] = []
        for it in items[:count]:
            ex = _reduce_question(it)
            if ex:
                examples.append(ex)
        logger.info("Few-shot: got %d example question(s).", len(examples))
        return examples
    except Exception as e:  # pragma: no cover - network path
        logger.info("Few-shot fetch failed (%s); skipping.", e)
        return []


def _items_from_envelope(data: Any) -> List[Dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "questions", "data", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def _reduce_question(q: Dict) -> Optional[Dict]:
    blocks = q.get("blocks")
    variants = q.get("variants")
    out: Dict[str, Any] = {}
    if isinstance(blocks, list):
        out["blocks"] = [
            {"value": b.get("value")} for b in blocks if isinstance(b, dict) and b.get("value")
        ]
    if isinstance(variants, list):
        reduced = []
        for v in variants:
            if isinstance(v, dict):
                reduced.append(
                    {
                        "value": v.get("value")
                        or (v.get("blocks") or [{}])[0].get("value")
                        if isinstance(v.get("blocks"), list)
                        else v.get("value"),
                        "is_correct": bool(v.get("is_correct")),
                    }
                )
        out["variants"] = reduced
    return out or None


def generate_for_section(
    client,
    model: str,
    subject: str,
    section_label: str,
    section_text: str,
    count: int,
    source: Optional[Dict] = None,
    fewshot: Optional[List[Dict]] = None,
    lang: str = "ru",
) -> List[Dict]:
    """Generate + normalize drafts for one section. Returns ready draft dicts."""
    user = build_generation_prompt(
        subject=subject,
        section_label=section_label,
        section_text=section_text,
        count=count,
        fewshot=fewshot,
        lang=lang,
    )
    try:
        parsed = call_json(
            client=client,
            model=model,
            system=GENERATION_SYSTEM,
            user=user,
            schema=GENERATION_SCHEMA,
        )
    except Exception as e:
        logger.error("Generation failed for section '%s': %s", section_label, e)
        return []

    raws = parsed.get("questions") if isinstance(parsed, dict) else parsed
    if not isinstance(raws, list):
        logger.error("Section '%s': model output had no questions list.", section_label)
        return []

    drafts, errors = normalize_many(raws, subject, source)
    for err in errors:
        logger.warning("Section '%s': dropped %s", section_label, err)
    logger.info(
        "Section '%s': %d/%d drafts valid.", section_label, len(drafts), len(raws)
    )
    return drafts
