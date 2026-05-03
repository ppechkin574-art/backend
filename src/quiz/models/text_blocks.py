from sqlalchemy import Column, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base
from quiz.dtos.enums import BlockType
from quiz.models.edu_content import Hint, Question, Variant


class TextBlockLink(Base):
    __tablename__ = "text_block_links"
    id = Column(Integer, primary_key=True)
    question_id = Column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=True, unique=True)
    hint_id = Column(ForeignKey("hints.id", ondelete="CASCADE"), nullable=True, unique=True)
    variant_id = Column(ForeignKey("variants.id", ondelete="CASCADE"), nullable=True, unique=True)

    question = relationship(Question, back_populates="link", uselist=False, passive_deletes=True)
    hint = relationship(Hint, back_populates="link", uselist=False, passive_deletes=True)
    variant = relationship(Variant, back_populates="link", uselist=False, passive_deletes=True)
    blocks = relationship(
        "TextBlock",
        back_populates="text_block_link",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TextBlock(Base):
    __tablename__ = "question_blocks"
    id = Column(Integer, primary_key=True)
    type = Column(Enum(BlockType), nullable=False, default=BlockType.text)
    order = Column(Integer, nullable=False)
    value = Column(String)
    text_block_link_id = Column(ForeignKey("text_block_links.id", ondelete="CASCADE"), nullable=False)

    text_block_link = relationship(TextBlockLink, back_populates="blocks", passive_deletes=True)
