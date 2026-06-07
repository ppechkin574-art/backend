"""Unit tests for the PURE functions — runnable WITHOUT any API key or network.

Covers:
  - chunk.chunk_text          (heading split + size-based sub-split)
  - dedup.similarity / best_match / flag_duplicates
  - draft_schema.normalize_draft / normalize_many (coercion + validation)

Run either way:
  pytest tools/question_generator/tests/test_pure.py
  python3 tools/question_generator/tests/test_pure.py
"""

from __future__ import annotations

import importlib.util
import os
import sys

# Load the three pure modules by file path so optional deps (anthropic,
# requests, pypdf) are never imported. This keeps the tests dependency-free.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_qgen_{name}", os.path.join(_PKG, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    # config is imported by dedup/draft_schema via relative import; pre-register
    # the package shim so those `from .config import ...` lines resolve.
    spec.loader.exec_module(mod)  # type: ignore
    return mod


# draft_schema and dedup do `from .config import ...`. Build a tiny package
# namespace so relative imports work when loading by path.
def _bootstrap_package():
    import types

    pkg_name = "tools_qgen_test_pkg"
    if pkg_name in sys.modules:
        return sys.modules[pkg_name]
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [_PKG]  # type: ignore
    sys.modules[pkg_name] = pkg

    for sub in ("config", "chunk", "dedup", "draft_schema"):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{sub}", os.path.join(_PKG, f"{sub}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{sub}"] = mod
        spec.loader.exec_module(mod)  # type: ignore
    return pkg


_bootstrap_package()
chunk = sys.modules["tools_qgen_test_pkg.chunk"]
dedup = sys.modules["tools_qgen_test_pkg.dedup"]
draft_schema = sys.modules["tools_qgen_test_pkg.draft_schema"]


# --------------------------------------------------------------------------- #
# chunk.chunk_text
# --------------------------------------------------------------------------- #
def test_chunk_empty():
    assert chunk.chunk_text("") == []
    assert chunk.chunk_text("   \n  ") == []


def test_chunk_splits_on_headings():
    text = (
        "# Введение\n"
        "Это первый раздел про что-то важное и достаточно длинное.\n\n"
        "Глава 1 Основы\n"
        "Тело второго раздела со своим содержанием и фактами.\n"
    )
    secs = chunk.chunk_text(text, max_chars=6000)
    assert len(secs) == 2
    assert "Введение" in secs[0].heading
    assert secs[0].index == 0 and secs[1].index == 1
    assert "первый раздел" in secs[0].text


def test_chunk_subsplits_long_body():
    para = ("Предложение номер. " * 30).strip()  # ~ a chunk of text
    body = "\n\n".join([para] * 6)  # well over 200 chars
    # All-caps short line is recognised as a heading.
    text = "РАЗДЕЛ A\n" + body
    secs = chunk.chunk_text(text, max_chars=200)
    assert len(secs) >= 2
    assert all(len(s.text) <= 200 for s in secs)
    # All sub-sections inherit the heading.
    assert all(s.heading == "РАЗДЕЛ A" for s in secs)


def test_chunk_no_headings_single_body():
    # Body must clear the min_chars (40) noise floor to survive.
    text = "Просто абзац без заголовков, но достаточно длинный, чтобы остаться."
    secs = chunk.chunk_text(text, max_chars=6000)
    assert len(secs) == 1
    assert secs[0].text.startswith("Просто абзац")


# --------------------------------------------------------------------------- #
# dedup
# --------------------------------------------------------------------------- #
def test_similarity_bounds():
    assert dedup.similarity("", "") == 1.0
    assert dedup.similarity("abc", "") == 0.0
    assert dedup.similarity("Столица Казахстана?", "столица казахстана") > 0.9


def test_similarity_low_for_different():
    s = dedup.similarity("Чему равна площадь круга?", "Кто написал Абай жолы?")
    assert s < 0.5


def test_best_match_picks_closest():
    existing = [
        (1, "Кто был первым президентом?"),
        (2, "Столица Казахстана — это какой город?"),
        (3, "Какова формула воды?"),
    ]
    ratio, qid, _ = dedup.best_match("Какой город — столица Казахстана?", existing)
    assert qid == 2  # closest by normalized difflib ratio
    assert ratio > 0.5


def test_flag_duplicates_annotates_and_sets_id():
    drafts = [
        {
            "blocks": [{"type": "text", "order": 0, "value": "Столица Казахстана?"}],
            "variants": [],
        },
        {
            "blocks": [{"type": "text", "order": 0, "value": "Совершенно другой вопрос про химию."}],
            "variants": [],
        },
    ]
    existing = [(42, "Столица Казахстана?")]
    n = dedup.flag_duplicates(drafts, existing, threshold=0.85)
    assert n == 1
    assert drafts[0]["dedup_of_question_id"] == 42
    assert "dedup_note" in drafts[0]["validation"]
    assert drafts[0]["validation"]["dedup_max_ratio"] >= 0.85
    # The dissimilar one gets a ratio but no note / id.
    assert "dedup_note" not in drafts[1].get("validation", {})
    assert "dedup_of_question_id" not in drafts[1]


def test_flag_duplicates_empty_existing():
    drafts = [{"blocks": [{"type": "text", "order": 0, "value": "X"}]}]
    assert dedup.flag_duplicates(drafts, []) == 0


# --------------------------------------------------------------------------- #
# draft_schema.normalize_draft
# --------------------------------------------------------------------------- #
def _valid_raw():
    return {
        "difficulty": "СРЕДНИЙ",
        "question_type": "single",
        "blocks": [{"type": "text", "value": "Сколько будет 2+2?"}],
        "variants": [
            {"value": "3", "is_correct": False},
            {"value": "4", "is_correct": True},
            {"value": "5", "is_correct": False},
        ],
        "explanation_ru": "2+2=4 по тексту.",
    }


def test_normalize_basic_coercion():
    out = draft_schema.normalize_draft(_valid_raw(), "Математика")
    assert out["subject_name"] == "Математика"
    assert out["difficulty"] == "medium"          # alias coerced
    assert out["question_type"] == "single_choice"  # alias coerced
    assert out["status"] == "draft"
    assert [b["order"] for b in out["blocks"]] == [0]
    assert out["blocks"][0]["type"] == "text"


def test_normalize_multi_correct_forces_multiple_choice():
    raw = _valid_raw()
    raw["question_type"] = "single_choice"  # contradicts 2 correct below
    raw["variants"] = [
        {"value": "A", "is_correct": True},
        {"value": "B", "is_correct": True},
        {"value": "C", "is_correct": False},
    ]
    out = draft_schema.normalize_draft(raw, "Биология")
    assert out["question_type"] == "multiple_choice"


def test_normalize_infers_type_when_missing():
    raw = _valid_raw()
    raw.pop("question_type", None)
    out = draft_schema.normalize_draft(raw, "Физика")
    assert out["question_type"] == "single_choice"


def test_normalize_unknown_difficulty_becomes_none():
    raw = _valid_raw()
    raw["difficulty"] = "невозможный"
    out = draft_schema.normalize_draft(raw, "X")
    assert out["difficulty"] is None


def test_normalize_rejects_no_blocks():
    raw = _valid_raw()
    raw["blocks"] = []
    raw.pop("question", None)
    try:
        draft_schema.normalize_draft(raw, "X")
        assert False, "expected DraftValidationError"
    except draft_schema.DraftValidationError:
        pass


def test_normalize_rejects_too_few_variants():
    raw = _valid_raw()
    raw["variants"] = [{"value": "only one", "is_correct": True}]
    try:
        draft_schema.normalize_draft(raw, "X")
        assert False
    except draft_schema.DraftValidationError:
        pass


def test_normalize_rejects_no_correct():
    raw = _valid_raw()
    for v in raw["variants"]:
        v["is_correct"] = False
    try:
        draft_schema.normalize_draft(raw, "X")
        assert False
    except draft_schema.DraftValidationError:
        pass


def test_normalize_variant_block_flatten_and_string_fallback():
    raw = _valid_raw()
    raw["variants"] = [
        {"blocks": [{"value": "вложенный текст"}], "is_correct": True},
        "просто строка",  # bare string -> not correct
    ]
    out = draft_schema.normalize_draft(raw, "X")
    assert out["variants"][0]["value"] == "вложенный текст"
    assert out["variants"][0]["is_correct"] is True
    assert out["variants"][1]["value"] == "просто строка"
    assert out["variants"][1]["is_correct"] is False


def test_normalize_many_collects_errors():
    raws = [_valid_raw(), {"blocks": [], "variants": []}]
    ok, errors = draft_schema.normalize_many(raws, "X")
    assert len(ok) == 1
    assert len(errors) == 1
    assert "draft #1" in errors[0]


# --------------------------------------------------------------------------- #
# JSON extraction (llm.extract_json is pure, but importing llm pulls no deps
# until make_client is called — safe to load by path).
# --------------------------------------------------------------------------- #
def _load_llm():
    spec = importlib.util.spec_from_file_location(
        "tools_qgen_test_pkg.llm", os.path.join(_PKG, "llm.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tools_qgen_test_pkg.llm"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_extract_json_plain_and_fenced_and_prose():
    llm = _load_llm()
    assert llm.extract_json('{"a": 1}') == {"a": 1}
    assert llm.extract_json('```json\n{"b": 2}\n```') == {"b": 2}
    assert llm.extract_json('Вот результат: {"c": [1,2,3]} конец.') == {"c": [1, 2, 3]}
    assert llm.extract_json('prefix [1, 2] suffix') == [1, 2]


def test_extract_json_raises_on_garbage():
    llm = _load_llm()
    try:
        llm.extract_json("no json here at all")
        assert False
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# Plain runner (no pytest needed)
# --------------------------------------------------------------------------- #
def _run_all():
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", name, "->", repr(e))
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
