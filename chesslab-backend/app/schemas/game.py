from datetime import datetime
from pydantic import BaseModel, ConfigDict


class GameResponse(BaseModel):
    id: str
    time_class: str | None
    color: str | None
    result: str | None
    opening_eco: str | None
    opening_name: str | None
    player_rating: int | None
    opponent_rating: int | None
    opponent_username: str | None
    played_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class OpeningStat(BaseModel):
    """Resposta da rota que responde 'onde falho nas aberturas'."""
    opening_eco: str
    opening_name: str
    games_played: int
    wins: int
    losses: int
    draws: int
    win_rate: float
    color: str | None = None  # None = agregado das duas cores


class SyncResponse(BaseModel):
    games_found: int
    games_imported: int
    message: str
