import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["Content"])

_BENEFITS_RU = [
    {"id": 1, "position": 1, "title": "Пробное ЕНТ", "description": "Подготовка к экзамену в формате тестирования"},
    {"id": 2, "position": 2, "title": "Полный Курс", "description": "Комплексное обучение по всем темам с нуля"},
    {"id": 3, "position": 3, "title": "Кешбек", "description": "Возврат части средств за выполненные задания"},
    {"id": 4, "position": 4, "title": "Ежедневные задания", "description": "Регулярная практика для закрепления знаний"},
    {"id": 5, "position": 5, "title": "Повышающий КЕФ", "description": "Увеличение бонуса за активность и результаты"},
    {"id": 6, "position": 6, "title": "Родительский доступ", "description": "Контроль успеваемости и активности ученика"},
]

_BENEFITS_KZ = [
    {"id": 1, "position": 1, "title": "ҰБТ сынақ тапсырмасы", "description": "Емтихан форматында тест тапсыру арқылы дайындық"},
    {"id": 2, "position": 2, "title": "Толық курс", "description": "Барлық тақырыптар бойынша нөлден кешенді оқу"},
    {"id": 3, "position": 3, "title": "Кэшбэк", "description": "Орындалған тапсырмалар үшін қаражатты қайтару"},
    {"id": 4, "position": 4, "title": "Күнделікті тапсырмалар", "description": "Білімді бекіту үшін тұрақты жаттығу"},
    {"id": 5, "position": 5, "title": "Арттыру коэффициенті", "description": "Белсенділік пен нәтижелер үшін бонусты арттыру"},
    {"id": 6, "position": 6, "title": "Ата-ана қолжетімділігі", "description": "Оқушының үлгерімі мен белсенділігін бақылау"},
]


@router.get("/subscription-benefits", summary="Преимущества подписки PRO")
async def get_subscription_benefits(lang: str = "ru") -> list[dict]:
    """Возвращает список преимуществ подписки PRO на нужном языке.
    lang: 'ru' (по умолчанию) или 'kz'."""
    if lang.lower() in ("kz", "kk"):
        return _BENEFITS_KZ
    return _BENEFITS_RU
