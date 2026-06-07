"""Prompt builders for generation, verification, and OCR.

The generation prompt is schema-aware: it instructs the model to output the
exact draft JSON shape the backend accepts, grounded strictly in the supplied
section text (no outside facts), in Russian, with LaTeX for formulas, mixing
single- and multiple-choice where natural.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

# JSON Schema for structured generation output (one object: {"questions": [...]}).
# Constraint-light per structured-output limits (no min/max, no recursion).
GENERATION_SCHEMA: Dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic_name": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "question_type": {
                        "type": "string",
                        "enum": ["single_choice", "multiple_choice"],
                    },
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": ["text", "media"]},
                                "order": {"type": "integer"},
                                "value": {"type": "string"},
                            },
                            "required": ["type", "order", "value"],
                        },
                    },
                    "variants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "value": {"type": "string"},
                                "is_correct": {"type": "boolean"},
                            },
                            "required": ["value", "is_correct"],
                        },
                    },
                    "task_description": {"type": "string"},
                    "question_translation": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": [
                    "difficulty",
                    "question_type",
                    "blocks",
                    "variants",
                    "explanation",
                ],
            },
        }
    },
    "required": ["questions"],
}


VERIFICATION_SCHEMA: Dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "key_correct": {"type": "boolean"},
        "key_unique": {"type": "boolean"},
        "distractors_plausible": {"type": "boolean"},
        "grounded": {"type": "boolean"},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": [
        "key_correct",
        "key_unique",
        "distractors_plausible",
        "grounded",
        "confidence",
        "notes",
    ],
}


_LANG_NAMES = {"ru": "русском", "kk": "казахском"}


def lang_name(lang: str) -> str:
    return _LANG_NAMES.get((lang or "ru").lower(), "русском")


def generation_system(lang: str = "ru") -> str:
    ln = lang_name(lang)
    return (
        "Ты — методист, составляющий вопросы для ЕНТ (Единого национального "
        f"тестирования Республики Казахстан). Ты пишешь СТРОГО на {ln} языке — "
        f"текст вопроса, ВСЕ варианты ответа и объяснение должны быть на {ln} "
        "языке (математические формулы остаются в LaTeX). "
        "Ты создаёшь корректные тестовые задания с одним или несколькими "
        "правильными ответами (MCQ), опираясь ИСКЛЮЧИТЕЛЬНО на предоставленный "
        "фрагмент учебника. Запрещено использовать факты, которых нет в тексте. "
        "Если в тексте есть формулы — записывай их в LaTeX (внутри $...$). "
        "ВАЖНО: в JSON все обратные слэши LaTeX экранируй как \\\\ "
        "(например \\\\frac, \\\\sqrt), иначе JSON сломается. "
        "Каждый вопрос должен иметь ровно один однозначный ключ для single_choice, "
        "и два-три правильных варианта для multiple_choice — только когда это "
        "естественно вытекает из материала. Дистракторы (неверные варианты) "
        "должны быть правдоподобными, но однозначно неверными по тексту."
    )


# Back-compat alias (RU). Prefer generation_system(lang).
GENERATION_SYSTEM = generation_system("ru")


def build_generation_prompt(
    subject: str,
    section_label: str,
    section_text: str,
    count: int,
    fewshot: Optional[List[Dict]] = None,
    lang: str = "ru",
) -> str:
    """User message for one section's generation call."""
    shape = {
        "questions": [
            {
                "topic_name": "тема (по тексту, кратко)",
                "difficulty": "easy|medium|hard",
                "question_type": "single_choice|multiple_choice",
                "blocks": [{"type": "text", "order": 0, "value": "текст вопроса"}],
                "variants": [
                    {"value": "вариант A", "is_correct": True},
                    {"value": "вариант B", "is_correct": False},
                    {"value": "вариант C", "is_correct": False},
                    {"value": "вариант D", "is_correct": False},
                ],
                "task_description": "формулировка задания (необязательно)",
                "question_translation": "перефразировка вопроса (необязательно)",
                "explanation": "почему ключ верен, со ссылкой на текст",
            }
        ]
    }
    ln = lang_name(lang)
    parts: List[str] = []
    parts.append(f"Предмет: {subject}")
    parts.append(f"Раздел: {section_label}")
    parts.append(
        f"Сгенерируй ровно {count} тестовых заданий ЕНТ по фрагменту ниже."
    )
    parts.append(
        "Требования:\n"
        f"- Весь вывод (текст вопроса, варианты, объяснение) — ТОЛЬКО на {ln} языке.\n"
        "- Строго по тексту фрагмента, без внешних знаний.\n"
        "- 4 варианта ответа на каждый вопрос (если естественно — больше).\n"
        "- Смешивай single_choice и multiple_choice там, где это уместно.\n"
        "- Для multiple_choice должно быть 2–3 правильных варианта.\n"
        "- Формулы — в LaTeX ($...$); обратные слэши в JSON экранируй как \\\\.\n"
        "- explanation обязателен и должен ссылаться на текст.\n"
        "- difficulty оцени честно (easy/medium/hard)."
    )
    if fewshot:
        parts.append(
            "Примеры стиля существующих вопросов этого предмета "
            "(для тона и формата, НЕ копируй содержание):"
        )
        parts.append(json.dumps(fewshot, ensure_ascii=False, indent=2)[:4000])
    parts.append("Форма ответа (JSON, ключ верхнего уровня — questions):")
    parts.append(json.dumps(shape, ensure_ascii=False, indent=2))
    parts.append("=== ФРАГМЕНТ УЧЕБНИКА ===")
    parts.append(section_text)
    parts.append("=== КОНЕЦ ФРАГМЕНТА ===")
    return "\n\n".join(parts)


VERIFICATION_SYSTEM = (
    "Ты — строгий рецензент тестовых заданий ЕНТ. Тебе дают исходный фрагмент "
    "учебника и один сгенерированный вопрос. Проверь по тексту: (1) верен ли "
    "помеченный ключ; (2) для single_choice — единственный ли он правильный "
    "(key_unique); (3) правдоподобны и однозначно неверны ли дистракторы; "
    "(4) обоснован ли вопрос текстом (grounded), без внешних фактов. Дай "
    "числовую уверенность confidence в [0,1] и краткие notes на русском. "
    "Будь придирчив: при сомнении снижай confidence."
)


def build_verification_prompt(section_text: str, draft: Dict) -> str:
    """User message for verifying a single draft against its section."""
    compact = {
        "question_type": draft.get("question_type"),
        "blocks": draft.get("blocks"),
        "variants": draft.get("variants"),
        "explanation": draft.get("explanation_ru") or draft.get("explanation_kk"),
    }
    return (
        "Проверь вопрос строго по фрагменту. Ответь JSON по схеме "
        "{key_correct, key_unique, distractors_plausible, grounded, "
        "confidence, notes}.\n\n"
        "=== ФРАГМЕНТ ===\n"
        + section_text
        + "\n=== КОНЕЦ ФРАГМЕНТА ===\n\n"
        + "=== ВОПРОС ===\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
        + "\n=== КОНЕЦ ВОПРОСА ==="
    )


OCR_SYSTEM = (
    "Ты — точный OCR-движок для отсканированных страниц учебника на русском "
    "(и иногда казахском) языке. Извлеки ВЕСЬ текст со страницы дословно, "
    "сохраняя абзацы и заголовки. Математические формулы записывай в LaTeX "
    "($...$). Не добавляй ничего от себя, не комментируй. Если страница пустая "
    "или нечитаема — верни пустую строку."
)

OCR_USER = (
    "Извлеки весь текст с этой страницы. Формулы — в LaTeX. "
    "Верни только текст, без пояснений."
)
