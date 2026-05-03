import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TemplateLoader:
    """Загрузчик и рендерер HTML-email шаблонов"""

    TEMPLATE_MAPPING = {
        "email_verification": "email_verification.html",
        "password_reset": "password_reset.html",
        # "welcome": "welcome_email.html",
    }

    def __init__(self, templates_dir: str = None):
        if templates_dir is None:
            current_dir = Path(__file__).parent
            self.templates_dir = current_dir / "templates"
        else:
            self.templates_dir = Path(templates_dir)

        self._templates_cache = {}
        logger.info("TemplateLoader initialized with directory: %s", self.templates_dir)

    def get_template_path(self, template_type: str) -> Path:
        """Получает путь к файлу шаблона по типу"""
        return self.templates_dir / self.TEMPLATE_MAPPING.get(template_type, f"{template_type}.html")

    def get_template(self, template_type: str) -> str:
        """Получает шаблон по типу"""
        if template_type in self._templates_cache:
            return self._templates_cache[template_type]

        template_path = self.get_template_path(template_type)

        if not template_path.exists():
            logger.warning("Template %s not found, using default", template_type)
            template_path = self.templates_dir / "email_verification.html"

        try:
            with open(template_path, encoding="utf-8") as file:
                template_content = file.read()
                self._templates_cache[template_type] = template_content
                logger.debug("Template loaded: %s", template_type)
                return template_content
        except Exception as e:
            logger.exception("Error loading template %s: %s", template_type, e)
            raise

    def render_template(self, template_type: str, **variables: dict[str, Any]) -> str:
        """Рендерит шаблон с переданными переменными"""
        template = self.get_template(template_type)

        try:
            rendered = template
            for key, value in variables.items():
                placeholder = "{{ " + key + " }}"
                rendered = rendered.replace(placeholder, str(value))

            logger.debug("Template rendered: %s", template_type)
            return rendered
        except Exception as e:
            logger.exception("Error rendering template %s: %s", template_type, e)
            raise
