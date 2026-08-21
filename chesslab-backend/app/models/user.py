import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    # username público do Chess.com, preenchido no onboarding (fase 2)
    chesscom_username = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    games = relationship("Game", back_populates="owner", cascade="all, delete-orphan")
    review_cards = relationship("ReviewCard", back_populates="owner", cascade="all, delete-orphan")
