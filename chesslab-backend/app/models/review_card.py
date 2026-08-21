import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class ReviewCard(Base):
    """
    Cada card representa uma posição (linha de abertura, por agora) que o
    jogador errou e precisa de reforçar. Campos seguem a lógica do SM-2
    (mesmo algoritmo do Anki): repetitions, ease_factor e interval_days
    juntos decidem quando o card volta a aparecer.
    """
    __tablename__ = "review_cards"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    source_game_id = Column(String, ForeignKey("games.id"), nullable=True)

    fen = Column(String, nullable=False)          # posição antes do erro
    correct_move = Column(String, nullable=False)  # lance correto em SAN ou UCI
    opening_eco = Column(String, nullable=True)

    # estado do algoritmo de repetição espaçada
    repetitions = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    interval_days = Column(Integer, default=0)

    next_review_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_reviewed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="review_cards")
