from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 'banner' — отображается в главном карусельном баннере
    # 'card'   — отображается в сетке «События»
    type = Column(String(20), nullable=False)
    badge_text = Column(String(100), nullable=False)    # "СОБЫТИЕ МЕСЯЦА"
    badge_text_kk = Column(String(100), nullable=True) # KK: "АЙ ОҚИҒАСЫ"
    title = Column(String(300), nullable=False)         # "Большой турнир"
    title_kk = Column(String(300), nullable=True)       # KK
    prize_text = Column(String(100), nullable=True)     # "5 000 000 ₸"
    prize_text_kk = Column(String(100), nullable=True)  # KK
    subtitle = Column(Text, nullable=True)              # "Борись за …"
    subtitle_kk = Column(Text, nullable=True)           # KK
    secondary_text = Column(String(300), nullable=True) # "Победитель получит планшет"
    secondary_text_kk = Column(String(300), nullable=True) # KK
    deadline = Column(DateTime(timezone=True), nullable=True)  # для таймера обратного отсчёта
    button_text = Column(String(100), nullable=True)    # "Подробнее →" (только для banner)
    button_text_kk = Column(String(100), nullable=True) # KK
    bg_color = Column(String(20), nullable=True)        # hex: "#5B2EC4"
    icon_url = Column(String(500), nullable=True)       # MinIO object key: "event-icons/uuid.png"
    progress_current = Column(Integer, nullable=True)   # 12340
    progress_max = Column(Integer, nullable=True)       # 50000
    sort_order = Column(Integer, nullable=False, server_default="0")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
