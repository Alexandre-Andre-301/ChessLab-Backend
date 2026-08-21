from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.game import Game
from app.schemas.game import SyncResponse
from app.services.auth_service import get_current_user
from app.services import chesscom_client, pgn_parser

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/chesscom", response_model=SyncResponse)
def sync_chesscom_games(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.chesscom_username:
        raise HTTPException(
            status_code=400,
            detail="Conecta primeiro o teu username do Chess.com em /users/me/chesscom",
        )

    try:
        raw_games = chesscom_client.get_all_games(current_user.chesscom_username)
    except chesscom_client.ChessComError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # ids já existentes no DB pra este user, evita reprocessar tudo a cada sync
    existing_ids = {
        row[0]
        for row in db.query(Game.chesscom_game_id).filter(Game.owner_id == current_user.id).all()
    }

    imported = 0
    for raw_game in raw_games:
        parsed = pgn_parser.parse_game(raw_game, current_user.chesscom_username)

        if parsed["chesscom_game_id"] in existing_ids:
            continue  # já temos esta partida, não duplica

        game = Game(owner_id=current_user.id, **parsed)
        db.add(game)
        imported += 1

    db.commit()

    return SyncResponse(
        games_found=len(raw_games),
        games_imported=imported,
        message=f"{imported} novas partidas importadas de {len(raw_games)} encontradas.",
    )
