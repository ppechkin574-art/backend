"""Store step: POST drafts to /admin/question-drafts (or write JSON on dry-run).

Per-draft try/except — a single failure is logged and skipped, never aborts
the batch. Existing-question fetch (for dedup) also lives here.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_OUTPUT_FILE, get_logger

logger = get_logger("qgen.store")

DRAFTS_ENDPOINT = "/admin/question-drafts"
QUESTIONS_ENDPOINT = "/admin/questions"


def write_dry_run(drafts: List[Dict], path: str = DEFAULT_OUTPUT_FILE) -> str:
    """Write the draft payloads to a JSON file instead of POSTing."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"count": len(drafts), "drafts": drafts},
            fh,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("Dry run: wrote %d draft(s) to %s", len(drafts), path)
    return path


def post_drafts(
    drafts: List[Dict],
    api_url: str,
    admin_token: str,
    timeout: int = 60,
) -> Tuple[int, int]:
    """POST each draft. Returns (succeeded, failed). Never raises per-item."""
    import requests  # lazy

    url = api_url.rstrip("/") + DRAFTS_ENDPOINT
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    }
    succeeded = 0
    failed = 0
    for i, draft in enumerate(drafts):
        try:
            resp = requests.post(url, headers=headers, json=draft, timeout=timeout)
            if resp.status_code in (200, 201):
                succeeded += 1
                new_id = _safe_id(resp)
                logger.info("Posted draft %d/%d -> id=%s", i + 1, len(drafts), new_id)
            else:
                failed += 1
                logger.error(
                    "Draft %d/%d failed: HTTP %s %s",
                    i + 1,
                    len(drafts),
                    resp.status_code,
                    resp.text[:300],
                )
        except Exception as e:  # pragma: no cover - network path
            failed += 1
            logger.error("Draft %d/%d errored: %s", i + 1, len(drafts), e)
    logger.info("Store: %d posted, %d failed.", succeeded, failed)
    return succeeded, failed


def _safe_id(resp) -> Optional[int]:
    try:
        return resp.json().get("id")
    except Exception:
        return None


def fetch_existing_questions(
    api_url: str,
    admin_token: str,
    subject_name: Optional[str] = None,
    limit: int = 500,
    timeout: int = 60,
) -> List[Tuple[Optional[int], str]]:
    """Fetch existing questions' (id, text) for dedup. Best-effort -> [].

    Defensive about envelope shape and block layout.
    """
    try:
        import requests  # lazy

        params: Dict = {"limit": limit}
        if subject_name:
            params["search"] = subject_name
        resp = requests.get(
            api_url.rstrip("/") + QUESTIONS_ENDPOINT,
            headers={"Authorization": f"Bearer {admin_token}"},
            params=params,
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.info("Existing-questions fetch HTTP %s; dedup skipped.", resp.status_code)
            return []
        data = resp.json()
        items = _items(data)
        out: List[Tuple[Optional[int], str]] = []
        for q in items:
            qid = q.get("id")
            text = _question_text(q)
            if text:
                out.append((qid, text))
        logger.info("Fetched %d existing question(s) for dedup.", len(out))
        return out
    except Exception as e:  # pragma: no cover - network path
        logger.info("Existing-questions fetch failed (%s); dedup skipped.", e)
        return []


def _items(data) -> List[Dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "questions", "data", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def _question_text(q: Dict) -> str:
    parts: List[str] = []
    blocks = q.get("blocks")
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict) and b.get("value") and b.get("type", "text") == "text":
                parts.append(str(b["value"]))
    if not parts:
        for key in ("question", "text", "title"):
            if isinstance(q.get(key), str):
                parts.append(q[key])
                break
    return " ".join(parts)
