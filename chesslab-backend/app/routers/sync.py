from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
import httpx

from app.database import get_db
from app.models.user import User
from app.models.game import Game
from app.schemas.game import SyncResponse
from app.services.auth_service import get_current_user
from app.services import chesscom_client, pgn_parser

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/chesscom", response_model=SyncResponse)
def sync_chesscom_games(
    months: int | None = Query(default=None, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.chesscom_username:
        raise HTTPException(
            status_code=400,
            detail="Conecta primeiro o teu username do Chess.com em /users/me/chesscom",
        )

    try:
        raw_games = chesscom_client.get_all_games(
            current_user.chesscom_username, limit_months=months
        )
    except chesscom_client.ChessComError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="O Chess.com não respondeu. Tenta de novo daqui a pouco.",
        )

    # ids já existentes no DB pra este user, evita reprocessar tudo a cada sync
    existing_ids = {
        row[0]
        for row in db.query(Game.chesscom_game_id).filter(Game.owner_id == current_user.id).all()
    }

    imported = 0
    skipped = 0
    for raw_game in raw_games:
        try:
            parsed = pgn_parser.parse_game(raw_game, current_user.chesscom_username)

            if not parsed["chesscom_game_id"]:
                skipped += 1
                continue

            if parsed["chesscom_game_id"] in existing_ids:
                continue  # já temos esta partida, não duplica

            game = Game(owner_id=current_user.id, **parsed)
            db.add(game)
            imported += 1
        except Exception:
            # partida com dados estranhos não pode rebentar o sync todo
            skipped += 1
            continue

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Não foi possível guardar as partidas.")

    return SyncResponse(
        games_found=len(raw_games),
        games_imported=imported,
        message=f"{imported} novas partidas importadas de {len(raw_games)} encontradas."
        + (f" ({skipped} ignoradas por dados inválidos.)" if skipped else ""),
    )
