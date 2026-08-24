from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.game import Game
from app.schemas.game import (
    GameDetailResponse,
    GameResponse,
    OpeningStat,
    RatingPoint,
    TimeClassStat,
)
from app.services.analytics import get_opening_stats, get_performance_by_time_class
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=list[GameResponse])
def list_games(
    time_class: str | None = Query(default=None),
    result: str | None = Query(default=None),
    color: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Game).filter(Game.owner_id == current_user.id)

    if time_class:
        query = query.filter(Game.time_class == time_class)
    if result:
        query = query.filter(Game.result == result)
    if color:
        query = query.filter(Game.color == color)

    games = (
        query.order_by(Game.played_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return games


@router.get("/openings/stats", response_model=list[OpeningStat])
def opening_stats(
    time_class: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    A rota que responde 'onde estou a falhar nas aberturas'.
    Agrupa variantes pela família (todas as Caro-Kann contam como Caro-Kann)
    e devolve win rate ordenado do pior pro melhor.
    """
    return get_opening_stats(db, current_user.id, time_class)


@router.get("/rating/history", response_model=list[RatingPoint])
def rating_history(
    time_class: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Evolução do rating ao longo do tempo, para o gráfico do perfil."""
    query = (
        db.query(Game.played_at, Game.player_rating)
        .filter(
            Game.owner_id == current_user.id,
            Game.played_at.isnot(None),
            Game.player_rating.isnot(None),
        )
        .order_by(Game.played_at.asc())
    )

    if time_class:
        query = query.filter(Game.time_class == time_class)

    return [
        RatingPoint(played_at=row.played_at, player_rating=row.player_rating)
        for row in query.all()
    ]


@router.get("/stats/performance", response_model=list[TimeClassStat])
def performance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Win rate agregado por ritmo de jogo (bullet/blitz/rapid/daily)."""
    return get_performance_by_time_class(db, current_user.id)


@router.get("/{game_id}", response_model=GameDetailResponse)
def get_game(
    game_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = (
        db.query(Game)
        .filter(Game.owner_id == current_user.id, Game.id == game_id)
        .first()
    )
    if game is None:
        raise HTTPException(status_code=404, detail="Partida não encontrada")
    return game
