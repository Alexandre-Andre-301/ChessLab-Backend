from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse, ConnectChessComRequest
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/chesscom", response_model=UserResponse)
def connect_chesscom(
    payload: ConnectChessComRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.chesscom_username = payload.chesscom_username
    db.commit()
    db.refresh(current_user)
    return current_user
