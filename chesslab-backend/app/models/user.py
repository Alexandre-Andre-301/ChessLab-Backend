import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, String, DateTime, Integer
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

    # username público do Chess.com, preenchido no onboarding
    chesscom_username = Column(String, nullable=True)

    # respostas do onboarding
    main_goal = Column(String, nullable=True)
    peak_rating = Column(Integer, nullable=True)
    onboarding_completed = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    games = relationship("Game", back_populates="owner", cascade="all, delete-orphan")
    review_cards = relationship("ReviewCard", back_populates="owner", cascade="all, delete-orphan")
