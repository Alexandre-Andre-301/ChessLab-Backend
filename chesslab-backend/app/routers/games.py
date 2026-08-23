from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.game import Game
from app.schemas.game import GameResponse, OpeningStat, RatingPoint
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/games", tags=["games"])

# palavras que marcam onde acaba o nome da família e começam as variantes
# ex.: "Caro Kann Defense 2.Nf3 d5 3.d3" -> família "Caro Kann Defense"
FAMILY_MARKERS = {
    "game",
    "opening",
    "defense",
    "defence",
    "attack",
    "gambit",
    "countergambit",
    "counter-gambit",
    "system",
    "variation",
    "accepted",
    "declined",
    "refused",
}


def _stem(token: str) -> str:
    return token.split(".")[0].strip(",").lower()


def opening_family(name: str | None) -> str | None:
    """Reduz 'Ruy Lopez Opening Morphy Defense Closed Variation...' a 'Ruy Lopez Opening'."""
    if not name:
        return None

    tokens = name.split()
    family: list[str] = []

    for i, token in enumerate(tokens):
        stem = _stem(token)

        if i > 0 and stem in FAMILY_MARKERS:
            family.append(token)

            # "Gambit Accepted/Declined/Refused" faz parte da família,
            # não é uma variante à parte
            if stem == "gambit" and i + 1 < len(tokens):
                nxt = _stem(tokens[i + 1])
                if nxt in {"accepted", "declined", "refused"}:
                    family.append(tokens[i + 1])
            break

        family.append(token)

    return " ".join(family)


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
    query = db.query(
        Game.opening_eco,
        Game.opening_name,
        Game.result,
    ).filter(
        Game.owner_id == current_user.id,
        Game.opening_eco.isnot(None),
    )

    if time_class:
        query = query.filter(Game.time_class == time_class)

    agg: dict[str, dict[str, int]] = {}
    eco_by_family: dict[str, str] = {}

    for eco, name, result in query.all():
        family = opening_family(name) or eco
        bucket = agg.setdefault(
            family, {"games_played": 0, "wins": 0, "losses": 0, "draws": 0}
        )
        bucket["games_played"] += 1
        if result == "win":
            bucket["wins"] += 1
        elif result == "draw":
            bucket["draws"] += 1
        else:
            bucket["losses"] += 1
        eco_by_family.setdefault(family, eco)

    stats = []
    for family, bucket in agg.items():
        games = bucket["games_played"]
        win_rate = round((bucket["wins"] / games) * 100, 1) if games else 0.0
        stats.append(
            OpeningStat(
                opening_eco=eco_by_family[family],
                opening_name=family,
                wins=bucket["wins"],
                losses=bucket["losses"],
                draws=bucket["draws"],
                games_played=games,
                win_rate=win_rate,
            )
        )

    # ordenado do pior win rate pro melhor — é literalmente "onde falhas primeiro"
    stats.sort(key=lambda s: s.win_rate)
    return stats


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
