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


class OAClient:
    """Marker client for an OpenAI-compatible provider (Groq / OpenRouter /
    Mistral / any /chat/completions endpoint). Talks raw HTTP via requests, so
    no extra SDK is needed."""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")


def make_client(api_key: Optional[str] = None, provider: str = "anthropic",
                base_url: Optional[str] = None):
    """Construct an LLM client for the chosen provider. Lazy imports so the
    pure functions/tests work without any SDK installed.

    - provider="anthropic" → Anthropic SDK client.
    - provider in {"groq","openai","openai-compatible"} → OAClient (HTTP).
    """
    if provider in ("groq", "openai", "openai-compatible"):
        if not base_url:
            base_url = "https://api.groq.com/openai/v1"
        return OAClient(api_key=api_key or "", base_url=base_url)

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


def _oa_post(url, headers, body, attempts: int = 4):
    """POST with retry/backoff on 429 (rate limit) and 5xx. Returns response."""
    import time

    import requests  # lazy

    last = None
    for i in range(attempts):
        resp = requests.post(url, headers=headers, json=body, timeout=120)
        if resp.status_code not in (429, 500, 502, 503):
            return resp
        last = resp
        try:
            wait = float(resp.headers.get("retry-after", ""))
        except ValueError:
            wait = 0.0
        wait = wait or min(20.0, 4.0 * (i + 1))
        logger.warning(
            "Groq %s — retry in %.0fs (attempt %d/%d)",
            resp.status_code, wait, i + 1, attempts,
        )
        time.sleep(wait)
    return last


def _oa_call_json(client, model, system, user, max_tokens) -> Any:
    """OpenAI-compatible (Groq/etc.) chat completion expecting JSON."""
    # Groq free tier rejects very large max_tokens (16000 → HTTP 413); 8000 is
    # safe and far more than a few questions need.
    max_tokens = min(max_tokens, 8000)
    body: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }
    url = f"{client.base_url}/chat/completions"
    resp = _oa_post(url, headers, body)
    if resp.status_code == 400:
        # Some models reject response_format — retry without it (extract_json
        # still recovers the JSON from the text).
        body.pop("response_format", None)
        resp = _oa_post(url, headers, body)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return extract_json(content)


def call_json(
    client,
    model: str,
    system: str,
    user: str,
    schema: Optional[Dict] = None,
    max_tokens: int = 16000,
    effort: str = "high",
) -> Any:
    """Make one call expected to return JSON; return the parsed object.

    Anthropic: output_config.format (schema) + adaptive thinking + streaming.
    OpenAI-compatible (Groq): chat/completions with response_format json_object.
    """
    if isinstance(client, OAClient):
        return _oa_call_json(client, model, system, user, max_tokens)

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
    if isinstance(client, OAClient):
        data_uri = f"data:{media_type};base64,{image_b64}"
        prompt = (system + "\n\n" + user) if system else user
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            "max_tokens": min(max_tokens, 8000),
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json",
        }
        resp = _oa_post(f"{client.base_url}/chat/completions", headers, body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

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
