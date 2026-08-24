from sqlalchemy import Column, Integer, String

from app.database import Base


class OpeningBook(Base):
    """
    Base de dados de aberturas (fonte: lichess-org/chess-openings).
    Uma linha por linha teórica ECO: código, nome, lances em UCI/SAN
    e família calculada ('Caro-Kann Defense', 'Sicilian Defense', ...).
    """
    __tablename__ = "opening_book"

    id = Column(Integer, primary_key=True, autoincrement=True)
    eco = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    family = Column(String, nullable=False, index=True)
    uci = Column(String, nullable=False)   # ex.: "e2e4 c7c5 g1f3"
    epd = Column(String, nullable=False, index=True, unique=True)
