from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    UserResponse,
    ConnectChessComRequest,
    OnboardingRequest,
)
from app.services.auth_service import get_current_user
from app.services.chesscom_client import ChessComError, get_player_profile

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


@router.put("/me/onboarding", response_model=UserResponse)
def complete_onboarding(
    payload: OnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    username = payload.chesscom_username.strip()

    try:
        get_player_profile(username)
    except ChessComError:
        raise HTTPException(
            status_code=400,
            detail=f"O username '{username}' não existe no Chess.com",
        )

    current_user.chesscom_username = username
    current_user.main_goal = payload.main_goal
    current_user.peak_rating = payload.peak_rating
    current_user.onboarding_completed = True
    db.commit()
    db.refresh(current_user)
    return current_user
