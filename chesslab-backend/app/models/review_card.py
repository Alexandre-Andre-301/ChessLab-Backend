import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class ReviewCard(Base):
    """
    Cada card representa uma posição para treinar com repetição espaçada
    (SM-2, como o Anki):

    - card_type="opening": posição do repertório do jogador (dos seus jogos),
      ele tem de acertar o lance que costuma jogar.
    - card_type="puzzle": posição tática dos seus jogos (mate em 1 ou
      captura que ganha material), ele tem de encontrar o melhor lance.
    """
    __tablename__ = "review_cards"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    source_game_id = Column(String, ForeignKey("games.id"), nullable=True)

    card_type = Column(String, nullable=False, default="opening")  # opening | puzzle

    fen = Column(String, nullable=False)           # posição antes do lance (4 campos)
    correct_move = Column(String, nullable=False)   # lance correto em SAN
    correct_move_uci = Column(String, nullable=True)  # mesmo lance em UCI (e2e4)
    opening_eco = Column(String, nullable=True)

    # estado do algoritmo de repetição espaçada
    repetitions = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    interval_days = Column(Integer, default=0)

    next_review_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_reviewed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="review_cards")
