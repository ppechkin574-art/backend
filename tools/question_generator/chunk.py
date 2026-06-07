"""Split ingested chapter text into sections. PURE functions (unit-tested).

Strategy:
1. Detect headings (markdown #, ALL-CAPS short lines, numbered headings like
   "5.2 Название", "Глава 5", "§3"). Each heading starts a new section.
2. Within a section, if the body exceeds `max_chars`, split it further on
   paragraph boundaries (blank lines), never mid-paragraph, so each emitted
   chunk stays under the size cap.

No network, no LLM — deterministic and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# Headings we recognise. Order matters only for readability.
_HEADING_PATTERNS = [
    re.compile(r"^\s{0,3}#{1,6}\s+\S"),                       # markdown  # Title
    re.compile(r"^\s*(глава|тарау|раздел|часть|§)\s*\.?\s*\d", re.IGNORECASE),  # Глава 5 / §3
    re.compile(r"^\s*\d+(\.\d+)*\.?\s+\S{3,}"),               # 5.2 Название
]


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for pat in _HEADING_PATTERNS:
        if pat.match(line):
            return True
    # Short ALL-CAPS line (a likely section title). Allow cyrillic.
    letters = [c for c in stripped if c.isalpha()]
    if (
        3 <= len(stripped) <= 80
        and letters
        and all((not c.isalpha()) or c.isupper() for c in stripped)
        and len(stripped.split()) <= 9
    ):
        return True
    return False


@dataclass
class Section:
    """One unit of source text handed to the generator."""

    heading: str
    text: str
    index: int = 0
    # Page span is best-effort; ingest may annotate it.
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.heading or "Без заголовка"


def _split_long_body(body: str, max_chars: int) -> List[str]:
    """Split an over-long body on paragraph boundaries, packing greedily."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paras:
        return []
    out: List[str] = []
    buf = ""
    for para in paras:
        # A single paragraph larger than the cap: hard-wrap on sentence ends.
        if len(para) > max_chars:
            if buf:
                out.append(buf.strip())
                buf = ""
            out.extend(_hard_wrap(para, max_chars))
            continue
        candidate = (buf + "\n\n" + para).strip() if buf else para
        if len(candidate) > max_chars and buf:
            out.append(buf.strip())
            buf = para
        else:
            buf = candidate
    if buf.strip():
        out.append(buf.strip())
    return out


def _hard_wrap(text: str, max_chars: int) -> List[str]:
    """Last-resort split of a huge paragraph on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?。])\s+", text)
    out: List[str] = []
    buf = ""
    for sent in sentences:
        candidate = (buf + " " + sent).strip() if buf else sent
        if len(candidate) > max_chars and buf:
            out.append(buf.strip())
            buf = sent
        else:
            buf = candidate
    if buf.strip():
        out.append(buf.strip())
    # If a single sentence is still too long, slice it.
    final: List[str] = []
    for piece in out:
        while len(piece) > max_chars:
            final.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            final.append(piece)
    return final


def chunk_text(
    text: str,
    max_chars: int = 6000,
    min_chars: int = 40,
) -> List[Section]:
    """Split chapter text into Section objects.

    Args:
        text: full cleaned chapter text.
        max_chars: soft cap per section body; larger bodies are sub-split.
        min_chars: sections shorter than this are dropped (noise / page nums).

    Returns:
        Ordered list of Section. Pure — same input -> same output.
    """
    if not text or not text.strip():
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    blocks: List[tuple] = []  # (heading, body_lines)
    cur_heading = ""
    cur_body: List[str] = []

    def flush():
        if cur_body or cur_heading:
            blocks.append((cur_heading, "\n".join(cur_body)))

    for line in lines:
        if _is_heading(line):
            flush()
            cur_heading = line.strip().lstrip("#").strip()
            cur_body = []
        else:
            cur_body.append(line)
    flush()

    # No headings found at all -> treat whole text as one body to split.
    if len(blocks) == 1 and blocks[0][0] == "" and len(blocks[0][1]) > max_chars:
        bodies = _split_long_body(blocks[0][1], max_chars)
        blocks = [("", b) for b in bodies]

    sections: List[Section] = []
    idx = 0
    for heading, body in blocks:
        body = body.strip()
        if not body and not heading:
            continue
        if len(body) <= max_chars:
            if len(body) < min_chars and not heading:
                continue
            sections.append(Section(heading=heading, text=body, index=idx))
            idx += 1
        else:
            for sub in _split_long_body(body, max_chars):
                if len(sub) < min_chars:
                    continue
                sections.append(Section(heading=heading, text=sub, index=idx))
                idx += 1

    return sections
