from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.review_card import ReviewCard
from app.services.auth_service import get_current_user
from app.services.card_generator import generate_cards
from app.services.spaced_repetition import apply_review

router = APIRouter(prefix="/training", tags=["training"])


class AnswerRequest(BaseModel):
    move_uci: str


def _card_summary(card: ReviewCard) -> dict:
    return {
        "id": card.id,
        "card_type": card.card_type,
        "fen": card.fen,
        "opening_eco": card.opening_eco,
        "repetitions": card.repetitions,
        "interval_days": card.interval_days,
    }


@router.post("/generate")
def generate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gera cartões de aberturas e puzzles a partir dos jogos importados."""
    result = generate_cards(db, current_user)
    return result


@router.get("/due")
def due_cards(
    card_type: str | None = Query(default=None),
    limit: int = Query(default=10, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ReviewCard)
        .filter(
            ReviewCard.owner_id == current_user.id,
            ReviewCard.next_review_at <= datetime.utcnow(),
        )
        .order_by(ReviewCard.next_review_at.asc())
    )

    if card_type in ("opening", "puzzle"):
        query = query.filter(ReviewCard.card_type == card_type)

    cards = query.limit(limit).all()
    return [_card_summary(card) for card in cards]


@router.post("/cards/{card_id}/answer")
def answer_card(
    card_id: str,
    payload: AnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = (
        db.query(ReviewCard)
        .filter(ReviewCard.owner_id == current_user.id, ReviewCard.id == card_id)
        .first()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    correct = bool(card.correct_move_uci) and payload.move_uci.lower() == card.correct_move_uci.lower()

    # fallback para puzzles: qualquer mate em 1 na posição também vale
    if not correct and card.card_type == "puzzle":
        try:
            import chess

            board = chess.Board(card.fen)
            move = chess.Move.from_uci(payload.move_uci)
            if move in board.legal_moves:
                board.push(move)
                correct = board.is_checkmate()
                board.pop()
        except Exception:
            pass

    apply_review(card, correct)
    db.commit()

    return {
        "correct": correct,
        "correct_move": card.correct_move,
        "interval_days": card.interval_days,
        "next_review_at": card.next_review_at.isoformat(),
    }


@router.get("/overview")
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Totais para o ecrã principal do treino."""
    base = db.query(ReviewCard).filter(ReviewCard.owner_id == current_user.id)

    def counts(card_type: str):
        total = base.filter(ReviewCard.card_type == card_type).count()
        due = (
            base.filter(
                ReviewCard.card_type == card_type,
                ReviewCard.next_review_at <= datetime.utcnow(),
            ).count()
        )
        return {"total": total, "due": due}

    return {"opening": counts("opening"), "puzzle": counts("puzzle")}
