"""CLI entry point: ingest -> chunk -> generate -> verify -> dedup -> store.

Run:
  python -m tools.question_generator --book chapter.pdf \
      --subject "История Казахстана" --chapter "Глава 5" --count 3 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Dict, List, Optional

from . import __version__
from .chunk import chunk_text
from .config import (
    DEFAULT_COUNT_PER_SECTION,
    DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_FEWSHOT_COUNT,
    DEFAULT_GEN_MODEL,
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_OCR_MODEL,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_VERIFY_MODEL,
    ENV_ADMIN_TOKEN,
    ENV_ANTHROPIC_KEY,
    ENV_API_URL,
    get_logger,
    load_dotenv_if_available,
    read_env,
)

logger = get_logger("qgen")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="question_generator",
        description=(
            "Ingest a textbook chapter, generate ЕНТ MCQ drafts with Claude, "
            "verify, optionally dedup, and POST them as drafts to the backend."
        ),
    )
    p.add_argument("--book", required=True, help="Path to chapter file (.pdf/.txt/.md)")
    p.add_argument("--subject", required=True, help='Subject name, e.g. "История Казахстана"')
    p.add_argument("--chapter", required=True, help='Chapter label, e.g. "Глава 5"')
    p.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT_PER_SECTION,
        help="Questions to generate per section (default: %(default)s)",
    )
    p.add_argument("--lang", default="ru", help="Output language (default: ru)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Write drafts to JSON file instead of POSTing",
    )
    p.add_argument(
        "--out",
        default=DEFAULT_OUTPUT_FILE,
        help="Dry-run output file (default: %(default)s)",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit number of PDF pages ingested",
    )
    p.add_argument(
        "--max-chunk-chars",
        type=int,
        default=DEFAULT_MAX_CHUNK_CHARS,
        help="Soft cap on section size (default: %(default)s)",
    )
    p.add_argument("--gen-model", default=DEFAULT_GEN_MODEL, help="Generation model id")
    p.add_argument("--verify-model", default=DEFAULT_VERIFY_MODEL, help="Verification model id")
    p.add_argument("--ocr-model", default=DEFAULT_OCR_MODEL, help="Vision OCR model id")
    p.add_argument("--no-verify", action="store_true", help="Skip the verification pass")
    p.add_argument("--no-dedup", action="store_true", help="Skip dedup against existing questions")
    p.add_argument(
        "--no-fewshot",
        action="store_true",
        help="Skip fetching real questions for style few-shot",
    )
    p.add_argument(
        "--dedup-threshold",
        type=float,
        default=DEFAULT_DEDUP_THRESHOLD,
        help="Similarity ratio to flag a near-duplicate (default: %(default)s)",
    )
    p.add_argument(
        "--book-title",
        default=None,
        help="Override 'source.book' (defaults to the file name)",
    )
    p.add_argument("--verbose", action="store_true", help="Debug logging")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        get_logger("qgen", level=logging.DEBUG)
        for sub in ("ingest", "generate", "verify", "dedup", "store", "llm"):
            get_logger(f"qgen.{sub}", level=logging.DEBUG)

    load_dotenv_if_available()
    api_key = read_env(ENV_ANTHROPIC_KEY)
    admin_token = read_env(ENV_ADMIN_TOKEN)
    api_url = read_env(ENV_API_URL)

    # --- Credential preconditions -------------------------------------------
    if not api_key:
        logger.error(
            "%s is not set. Get one at the Anthropic Console and export it.",
            ENV_ANTHROPIC_KEY,
        )
        return 2
    if not args.dry_run:
        missing = [
            n for n, v in ((ENV_ADMIN_TOKEN, admin_token), (ENV_API_URL, api_url)) if not v
        ]
        if missing:
            logger.error(
                "Missing env for POST mode: %s. Use --dry-run to write a file instead.",
                ", ".join(missing),
            )
            return 2

    # --- Build Anthropic client ---------------------------------------------
    try:
        from .llm import make_client

        client = make_client(api_key)
    except Exception as e:
        logger.error("Could not initialize Anthropic client: %s", e)
        return 2

    book_title = args.book_title or args.book.split("/")[-1]
    source = {"book": book_title, "chapter": args.chapter, "page": None}

    # --- 1. Ingest -----------------------------------------------------------
    from .ingest import ingest_chapter

    try:
        text = ingest_chapter(
            path=args.book,
            client=client,
            ocr_model=args.ocr_model,
            max_pages=args.max_pages,
        )
    except FileNotFoundError:
        logger.error("Chapter file not found: %s", args.book)
        return 2
    except Exception as e:
        logger.error("Ingest failed: %s", e)
        return 1
    if not text.strip():
        logger.error("No text extracted from %s.", args.book)
        return 1

    # --- 2. Chunk ------------------------------------------------------------
    sections = chunk_text(text, max_chars=args.max_chunk_chars)
    if not sections:
        logger.error("Chunking produced 0 sections.")
        return 1
    logger.info("Chunked into %d section(s).", len(sections))

    # --- 3. Few-shot (best-effort) ------------------------------------------
    fewshot: List[Dict] = []
    if not args.no_fewshot and admin_token and api_url:
        from .generate import fetch_fewshot

        fewshot = fetch_fewshot(
            api_url, admin_token, args.subject, count=DEFAULT_FEWSHOT_COUNT
        )

    # --- 4. Generate ---------------------------------------------------------
    from .generate import generate_for_section

    all_pairs: List[Dict] = []  # {"draft": ..., "section_text": ...}
    for sec in sections:
        drafts = generate_for_section(
            client=client,
            model=args.gen_model,
            subject=args.subject,
            section_label=sec.label,
            section_text=sec.text,
            count=args.count,
            source=source,
            fewshot=fewshot,
            lang=args.lang,
        )
        for d in drafts:
            all_pairs.append({"draft": d, "section_text": sec.text})

    if not all_pairs:
        logger.error("Generation produced 0 valid drafts.")
        return 1
    logger.info("Generated %d valid draft(s) total.", len(all_pairs))

    drafts = [p["draft"] for p in all_pairs]

    # --- 5. Verify -----------------------------------------------------------
    if not args.no_verify:
        from .verify import verify_drafts

        verify_drafts(client, all_pairs, model=args.verify_model)

    # --- 6. Dedup (best-effort) ---------------------------------------------
    if not args.no_dedup and admin_token and api_url:
        from .dedup import flag_duplicates
        from .store import fetch_existing_questions

        existing = fetch_existing_questions(api_url, admin_token, subject_name=args.subject)
        flag_duplicates(drafts, existing, threshold=args.dedup_threshold)
    elif not args.no_dedup:
        logger.info("Dedup skipped (no admin token / API url).")

    # --- 7. Store ------------------------------------------------------------
    from .store import post_drafts, write_dry_run

    if args.dry_run:
        write_dry_run(drafts, args.out)
    else:
        succeeded, failed = post_drafts(drafts, api_url, admin_token)
        if failed and not succeeded:
            return 1

    logger.info("Done.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
