"""Central config: env vars, model defaults, logging, draft enum values.

Keeping the backend enum *string values* mirrored here (NOT importing the
backend) is deliberate — the tool is portable. If the backend enums change,
update the tuples below. They are asserted against the DTO contract in the
README and exercised by the unit tests.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# --- Env var names -----------------------------------------------------------
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_ADMIN_TOKEN = "AIMA_ADMIN_TOKEN"
ENV_API_URL = "AIMA_API_URL"

# --- Model defaults (overridable via CLI flags) ------------------------------
# Generation: Sonnet 4.6 — strong quality/cost for batch generation.
DEFAULT_GEN_MODEL = "claude-sonnet-4-6"
# Verification: Opus 4.8 — stricter, most-capable check pass.
DEFAULT_VERIFY_MODEL = "claude-opus-4-8"
# OCR / vision for scanned pages: Opus 4.8 (best vision + formula→LaTeX).
DEFAULT_OCR_MODEL = "claude-opus-4-8"

# --- Backend enum value contracts (mirror src/quiz/dtos/enums.py) ------------
# Difficulty enum values.
DIFFICULTIES = ("easy", "medium", "hard")
# QuestionType values we emit (the backend also has "matching", not used here).
QUESTION_TYPES = ("single_choice", "multiple_choice")
# BlockType values accepted by DraftBlock.
BLOCK_TYPES = ("text", "media", "video")

# --- Pipeline defaults -------------------------------------------------------
DEFAULT_COUNT_PER_SECTION = 3
DEFAULT_MAX_CHUNK_CHARS = 6000  # rough proxy for max-token chunk size
DEFAULT_DEDUP_THRESHOLD = 0.85  # difflib ratio above which we flag a near-dup
DEFAULT_OUTPUT_FILE = "drafts_output.json"
DEFAULT_FEWSHOT_COUNT = 3


def get_logger(name: str = "qgen", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def load_dotenv_if_available() -> None:
    """Best-effort: load a .env so the 3 env vars can live in a file.

    python-dotenv is optional; absence is not an error.
    """
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:  # pragma: no cover - optional dependency
        pass


def read_env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name, default)
    if val is not None:
        val = val.strip() or None
    return val
