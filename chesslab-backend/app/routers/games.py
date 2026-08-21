from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.game import Game
from app.schemas.game import GameResponse, OpeningStat
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
    Agrupa por ECO code e devolve win rate ordenado do pior pro melhor.
    """
    query = db.query(
        Game.opening_eco,
        Game.opening_name,
        func.count(Game.id).label("games_played"),
        func.sum(case((Game.result == "win", 1), else_=0)).label("wins"),
        func.sum(case((Game.result == "loss", 1), else_=0)).label("losses"),
        func.sum(case((Game.result == "draw", 1), else_=0)).label("draws"),
    ).filter(
        Game.owner_id == current_user.id,
        Game.opening_eco.isnot(None),
    )

    if time_class:
        query = query.filter(Game.time_class == time_class)

    rows = query.group_by(Game.opening_eco, Game.opening_name).all()

    stats = []
    for row in rows:
        win_rate = round((row.wins / row.games_played) * 100, 1) if row.games_played else 0.0
        stats.append(
            OpeningStat(
                opening_eco=row.opening_eco,
                opening_name=row.opening_name or row.opening_eco,
                games_played=row.games_played,
                wins=row.wins,
                losses=row.losses,
                draws=row.draws,
                win_rate=win_rate,
            )
        )

    # ordenado do pior win rate pro melhor — é literalmente "onde falhas primeiro"
    stats.sort(key=lambda s: s.win_rate)
    return stats
