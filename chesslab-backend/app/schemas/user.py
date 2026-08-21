from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    chesscom_username: str | None
    created_at: datetime

    # permite construir a partir do model SQLAlchemy diretamente
    model_config = ConfigDict(from_attributes=True)


class ConnectChessComRequest(BaseModel):
    chesscom_username: str
