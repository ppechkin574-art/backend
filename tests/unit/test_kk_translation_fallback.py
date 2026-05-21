"""Kazakh-text fallback at the DTO/block layer (Phase 7b).

Covers the pure helpers `localize_blocks_with_kk_text` (questions) and
`localize_hint_blocks_with_kk_text` (hints) added in
`src/quiz/dtos/questions.py` and `src/quiz/dtos/hint.py`.

Invariants under test
---------------------
1.  When `kk_text` is None/empty → blocks come back unchanged
    (identity preserved).  This is the RU fallback path.
2.  When a text block exists at the head → its `value` is swapped to
    the kk string, other blocks left intact, order preserved.
3.  When the first block is media (formula image / picture) → a new
    text block is prepended at order=0 and the rest shift down by one.
4.  When `kk_text` is set but the source list is empty → a single
    synthesised text block is returned.
"""

from quiz.dtos.enums import BlockType
from quiz.dtos.hint import localize_hint_blocks_with_kk_text
from quiz.dtos.questions import localize_blocks_with_kk_text
from quiz.dtos.text_blocks import TextBlockRepositoryDTO, TextBlockServiceDTO


def _text(order: int, value: str) -> TextBlockServiceDTO:
    return TextBlockServiceDTO(order=order, type=BlockType.text, value=value)


def _media(order: int, value: str = "https://cdn/example.png") -> TextBlockServiceDTO:
    return TextBlockServiceDTO(order=order, type=BlockType.media, value=value)


# ─────────────────────── question helper ───────────────────────


def test_no_kk_returns_blocks_unchanged() -> None:
    blocks = [_text(0, "Решите уравнение"), _media(1)]
    assert localize_blocks_with_kk_text(blocks, None) is blocks
    assert localize_blocks_with_kk_text(blocks, "") is blocks


def test_kk_text_replaces_first_text_block_value() -> None:
    blocks = [_text(0, "Решите уравнение"), _media(1), _text(2, "...")]
    out = localize_blocks_with_kk_text(blocks, "Теңдеуді шешіңіз")

    # First text block: value swapped, order/type/id preserved
    assert out[0].value == "Теңдеуді шешіңіз"
    assert out[0].order == 0
    assert out[0].type == BlockType.text
    # Media block untouched
    assert out[1].type == BlockType.media
    assert out[1].order == 1
    # Trailing text block NOT replaced — only the leading one is the
    # "question body"; subsequent text blocks usually carry auxiliary
    # captions that the JSON export doesn't translate separately.
    assert out[2].value == "..."


def test_kk_text_prepends_when_no_text_block_exists() -> None:
    blocks = [_media(0, "https://cdn/formula.png"), _media(1, "https://cdn/diagram.png")]
    out = localize_blocks_with_kk_text(blocks, "Кескінді қараңыз")

    assert len(out) == 3
    assert out[0].type == BlockType.text
    assert out[0].order == 0
    assert out[0].value == "Кескінді қараңыз"
    # Existing media blocks shifted down by one slot
    assert out[1].type == BlockType.media
    assert out[1].order == 1
    assert out[2].type == BlockType.media
    assert out[2].order == 2


def test_kk_text_on_empty_block_list_synthesises_single_block() -> None:
    out = localize_blocks_with_kk_text([], "Сұрақ")
    assert len(out) == 1
    assert out[0].type == BlockType.text
    assert out[0].order == 0
    assert out[0].value == "Сұрақ"


def test_blocks_are_not_mutated_in_place() -> None:
    blocks = [_text(0, "RU"), _media(1)]
    snapshot = [(b.order, b.type, b.value) for b in blocks]
    localize_blocks_with_kk_text(blocks, "KK")
    assert [(b.order, b.type, b.value) for b in blocks] == snapshot


# ─────────────────────── hint helper ───────────────────────


def _r_text(order: int, value: str) -> TextBlockRepositoryDTO:
    return TextBlockRepositoryDTO(order=order, type=BlockType.text, value=value)


def _r_media(order: int) -> TextBlockRepositoryDTO:
    return TextBlockRepositoryDTO(order=order, type=BlockType.media, value="img://x")


def test_hint_no_kk_returns_unchanged() -> None:
    blocks = [_r_text(0, "Правильный ответ: 0")]
    assert localize_hint_blocks_with_kk_text(blocks, None) is blocks


def test_hint_kk_swaps_first_text_block() -> None:
    blocks = [_r_text(0, "Правильный ответ: 0"), _r_media(1)]
    out = localize_hint_blocks_with_kk_text(blocks, "Дұрыс жауап: 0")

    assert out[0].value == "Дұрыс жауап: 0"
    assert out[0].type == BlockType.text
    assert out[1].type == BlockType.media


def test_hint_kk_prepends_when_only_media() -> None:
    blocks = [_r_media(0)]
    out = localize_hint_blocks_with_kk_text(blocks, "Түсіндірме")
    assert len(out) == 2
    assert out[0].value == "Түсіндірме"
    assert out[1].order == 1
