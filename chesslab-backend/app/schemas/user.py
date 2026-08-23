from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    chesscom_username: str | None
    main_goal: str | None
    peak_rating: int | None
    onboarding_completed: bool
    created_at: datetime

    # permite construir a partir do model SQLAlchemy diretamente
    model_config = ConfigDict(from_attributes=True)


class ConnectChessComRequest(BaseModel):
    chesscom_username: str


class OnboardingRequest(BaseModel):
    chesscom_username: str = Field(min_length=2, max_length=30)
    main_goal: str | None = Field(default=None, max_length=100)
    peak_rating: int | None = Field(default=None, ge=0, le=4000)
