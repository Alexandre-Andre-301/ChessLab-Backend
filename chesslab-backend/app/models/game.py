import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Game(Base):
    __tablename__ = "games"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # ID único da partida no Chess.com — chave pra evitar reimportar a mesma
    # partida em cada sync (é isto que responde à pergunta "já existe?")
    chesscom_game_id = Column(String, unique=True, index=True, nullable=False)

    pgn = Column(Text, nullable=False)

    # metadados extraídos do PGN, denormalizados aqui pra consultas rápidas
    # (evita ter de re-parsear o PGN toda vez que carregas a lista de jogos)
    time_class = Column(String, nullable=True)   # "blitz", "rapid", "bullet", "daily"
    color = Column(String, nullable=True)         # "white" ou "black"
    result = Column(String, nullable=True)        # "win", "loss", "draw"
    opening_eco = Column(String, nullable=True, index=True)  # ex: "B20"
    opening_name = Column(String, nullable=True)  # ex: "Sicilian Defense"

    player_rating = Column(Integer, nullable=True)
    opponent_rating = Column(Integer, nullable=True)
    opponent_username = Column(String, nullable=True)

    played_at = Column(DateTime, nullable=True)

    # marcador pra fase 3 (puzzles): já foi passado pelo Stockfish?
    analyzed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="games")
