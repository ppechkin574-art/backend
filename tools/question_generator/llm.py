"""Thin wrapper around the Anthropic SDK with robust JSON extraction.

All Claude calls go through here. We default to structured JSON output
(`output_config.format` with a json_schema) so parsing is reliable, and fall
back to brace-matching if a model ever returns prose around the JSON.

Adaptive thinking is used (per Opus 4.8 / Sonnet 4.6 guidance). We stream and
take the final message to avoid HTTP timeouts on larger generations.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import get_logger

logger = get_logger("qgen.llm")


def make_client(api_key: Optional[str] = None):
    """Construct an Anthropic client. Imported lazily so the rest of the tool
    (pure functions, tests) works without the SDK installed."""
    import anthropic  # noqa: WPS433 (lazy import is intentional)

    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY from env


def _extract_text(message) -> str:
    parts: List[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating prose/code fences.

    Tries: whole string -> ```json fenced block -> first balanced {...}/[...].
    Raises ValueError if nothing parses.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty model response")

    # 1) Whole thing.
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) Fenced code block.
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            text = candidate  # fall through to brace matching on the fence body

    # 3) First balanced object or array.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        snippet = text[start : i + 1]
                        try:
                            return json.loads(snippet)
                        except Exception:
                            break
    raise ValueError("could not extract JSON from model response")


def call_json(
    client,
    model: str,
    system: str,
    user: str,
    schema: Optional[Dict] = None,
    max_tokens: int = 16000,
    effort: str = "high",
) -> Any:
    """Make one Claude call expected to return JSON; return the parsed object.

    Uses output_config.format when a schema is given (guarantees valid JSON on
    supported models), adaptive thinking, and streaming for safety.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
    if schema is not None:
        kwargs["output_config"]["format"] = {
            "type": "json_schema",
            "schema": schema,
        }

    with client.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()

    text = _extract_text(message)
    return extract_json(text)


def call_vision_text(
    client,
    model: str,
    system: str,
    user: str,
    image_b64: str,
    media_type: str = "image/png",
    max_tokens: int = 8000,
    effort: str = "high",
) -> str:
    """OCR-style call: one image + instruction -> plain text. Returns text."""
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64,
            },
        },
        {"type": "text", "text": user},
    ]
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    ) as stream:
        message = stream.get_final_message()
    return _extract_text(message)
