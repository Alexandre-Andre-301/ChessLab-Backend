from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import httpx

from app.config import settings
from app.database import get_db
from app.models.opening_book import OpeningBook
from app.services import opening_book_service

router = APIRouter(prefix="/openings", tags=["openings"])

EXPLORER_HEADERS = {"User-Agent": "ChessLab/0.1 (opening advice)"}


def _explorer_url() -> str:
    return f"{settings.explorer_base_url}/lichess"


@router.post("/book/sync")
def sync_book(db: Session = Depends(get_db)):
    """Descarrega/atualiza a base ECO do Lichess (~3.500 linhas)."""
    try:
        total = opening_book_service.sync_book(db)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível descarregar a base de aberturas agora.",
        )
    return {"total": total}


@router.get("/book")
def book_lines(
    family: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=6, le=20),
    db: Session = Depends(get_db),
):
    """Linhas teóricas do livro: por família ou por pesquisa de nome."""
    query = db.query(OpeningBook)

    if family:
        query = query.filter(OpeningBook.family == family)
    if q:
        query = query.filter(OpeningBook.name.ilike(f"%{q}%"))

    lines = (
        query.order_by(OpeningBook.eco.asc(), OpeningBook.id.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "eco": line.eco,
            "name": line.name,
            "family": line.family,
            "uci_moves": line.uci.split(),
            "san_line": _san_from_uci(line.uci),
        }
        for line in lines
    ]


def _san_from_uci(uci: str) -> list[str]:
    """Converte a linha UCI do livro em SAN legível (ex.: e4 c5 Nf3 d6)."""
    try:
        import chess

        board = chess.Board()
        sans: list[str] = []
        for token in uci.split():
            move = chess.Move.from_uci(token)
            if move not in board.legal_moves:
                break
            sans.append(board.san(move))
            board.push(move)
        return sans
    except Exception:
        return []


@router.get("/explorer")
def explorer(
    fen: str = Query(...),
    speeds: str = Query(default="blitz,rapid"),
    ratings: str = Query(default="1200,1400,1600,1800"),
):
    """
    Proxy ao Lichess Explorer: popularidade real dos lances numa posição
    (jogos humanos, filtrado por ritmo e nível). Mantém a integração no
    backend conforme a arquitetura da spec.
    """
    try:
        response = httpx.get(
            _explorer_url(),
            params={"variant": "standard", "speeds": speeds, "ratings": ratings, "fen": fen},
            headers=EXPLORER_HEADERS,
            timeout=8,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Explorer indisponível neste momento.",
        )

    data = response.json()
    return {
        "total_games": data.get("total", 0),
        "moves": [
            {
                "san": move.get("san"),
                "games": (move.get("white", 0) + move.get("draws", 0) + move.get("black", 0)),
                "white_win_rate": _rate(move.get("white", 0), data.get("total", 0)),
                "draw_rate": _rate(move.get("draws", 0), data.get("total", 0)),
                "black_win_rate": _rate(move.get("black", 0), data.get("total", 0)),
            }
            for move in data.get("moves", [])[:6]
        ],
    }


def _rate(part: int, total: int) -> float:
    return round((part / total) * 100, 1) if total else 0.0
