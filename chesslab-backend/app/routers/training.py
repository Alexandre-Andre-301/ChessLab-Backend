from datetime import date, datetime, timedelta

import uuid

import chess
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.line_progress import LineProgress
from app.models.opening_book import OpeningBook
from app.models.user import User
from app.models.review_card import ReviewCard
from app.services import opening_book_service
from app.services.auth_service import get_current_user
from app.services.card_generator import generate_cards
from app.services.engine_service import (
    ENGINE_APPROVE_CP,
    best_move_san,
    interpret_loss,
    solid_moves,
    white_cp,
)
from app.services.explorer_client import (
    explorer_moves,
    ratings_band_for,
    sample_human_reply,
    win_rate_for,
)
from app.services.spaced_repetition import apply_review

router = APIRouter(prefix="/training", tags=["training"])


class AnswerRequest(BaseModel):
    move_uci: str
    hinted: bool = False   # revelámos a resposta? conta como falhado mas recupera um pouco


class LineMoveRequest(BaseModel):
    book_id: int
    uci: str
    color: str = "white"
    opponent: str = "book"          # book | human
    played_uci: list[str] = []      # linha real jogada até agora (para modo humano)


class LineCompleteRequest(BaseModel):
    book_id: int
    mistakes: int
    color: str = "white"


LEVEL_PLIES = 4  # níveis curtos estilo Lotus: 4 plies (2 lances teus + 2 do adversário)


def _ensure_families(db: Session, user_id: str) -> None:
    """Preenche família e cor dos cartões antigos (família via base ECO,
    cor derivada do FEN — a vez de quem joga é sempre o utilizador)."""
    cards = (
        db.query(ReviewCard)
        .filter(
            ReviewCard.owner_id == user_id,
            (ReviewCard.family.is_(None)) | (ReviewCard.color.is_(None)),
        )
        .all()
    )
    if not cards:
        return

    for card in cards:
        if card.family is None:
            card.family = opening_book_service.family_for_eco(db, card.opening_eco)
        if card.color is None:
            card.color = "white" if card.fen.split()[1] == "w" else "black"
    db.commit()


def _card_status(card: ReviewCard) -> str:
    if (card.repetitions or 0) == 0:
        return "learning"
    if (card.mastery or 0) >= 80:
        return "mastered"
    return "review"


def _card_summary(card: ReviewCard) -> dict:
    return {
        "id": card.id,
        "card_type": card.card_type,
        "fen": card.fen,
        "opening_eco": card.opening_eco,
        "family": card.family,
        "color": card.color or ("white" if card.fen.split()[1] == "w" else "black"),
        "repetitions": card.repetitions,
        "interval_days": card.interval_days,
        "occurrences": card.occurrences or 1,
        "line_moves": card.line_moves.split() if card.line_moves else [],
        "explanation": getattr(card, "explanation", None),
        "mastery": card.mastery or 0,
        "streak": card.streak or 0,
        "lapses": card.lapses or 0,
        "status": _card_status(card),
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
    family: str | None = Query(default=None),
    color: str | None = Query(default=None),
    limit: int = Query(default=10, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Training Scheduler (§22, §57): prioridade =
      fraqueza (1-mastery) × importância (frequência) × urgência (atraso)
    Novas posições (mastery 0) entram com prioridade alta naturalmente;
    dominadas (mastery ≥ 80) quase desaparecem.
    """
    _ensure_families(db, current_user.id)

    now = datetime.utcnow()
    query = db.query(ReviewCard).filter(ReviewCard.owner_id == current_user.id)

    if card_type in ("opening", "puzzle"):
        query = query.filter(ReviewCard.card_type == card_type)
    if family:
        query = query.filter(ReviewCard.family == family)
    if color in ("white", "black"):
        query = query.filter(ReviewCard.color == color)

    pool = query.all()
    scored = []
    for card in pool:
        mastery = (card.mastery or 0) / 100
        occurrences = card.occurrences or 1
        overdue = card.next_review_at is not None and card.next_review_at <= now
        is_new = (card.repetitions or 0) == 0

        if not overdue and not is_new and mastery >= 0.8:
            continue  # dominadas e em dia: não merecem sessão

        weakness = 1 - mastery
        importance = min(1.0, occurrences / 10)
        urgency = 1.5 if overdue else (1.0 if is_new else 0.4)
        priority = weakness * importance * urgency

        scored.append((priority, card))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    cards = [card for _p, card in scored[:limit]]
    return [_card_summary(card) for card in cards]


@router.get("/families")
def families(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Agrupa os cartões de aberturas por família E cor — a mesma abertura
    (ex.: Caro-Kann) aparece separada como brancas e como pretas.
    """
    _ensure_families(db, current_user.id)

    cards = (
        db.query(ReviewCard)
        .filter(
            ReviewCard.owner_id == current_user.id,
            ReviewCard.card_type == "opening",
        )
        .all()
    )

    agg: dict[tuple[str, str], dict] = {}
    now = datetime.utcnow()
    for card in cards:
        name = card.family or "Outras aberturas"
        color = card.color or "white"
        key = (name, color)
        bucket = agg.setdefault(
            key,
            {
                "family": name,
                "eco": card.opening_eco,
                "color": color,
                "total": 0,
                "due": 0,
                "mastery_weight": 0,
                "occurrences_sum": 0,
            },
        )
        bucket["total"] += 1
        occ = card.occurrences or 1
        bucket["mastery_weight"] += (card.mastery or 0) * occ
        bucket["occurrences_sum"] += occ
        if card.next_review_at and card.next_review_at <= now:
            bucket["due"] += 1

    result = []
    for bucket in agg.values():
        occ_sum = bucket.pop("occurrences_sum") or 1
        bucket["mastery"] = round(bucket.pop("mastery_weight") / occ_sum)
        result.append(bucket)

    result.sort(
        key=lambda f: (0 if f["color"] == "white" else 1, -f["due"], f["family"])
    )
    return result


@router.get("/line-session")
def line_session(
    family: str = Query(...),
    color: str = Query(default="white"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Treino de linha guiada estilo Lotus: escolhe a linha do livro ECO que
    melhor corresponde às partidas do utilizador nessa família e devolve
    todos os lances para o frontend guiar lance a lance.
    """
    _ensure_families(db, current_user.id)

    # ECO mais comum nos cartões do utilizador dentro da família
    eco_row = (
        db.query(ReviewCard.opening_eco, func.count(ReviewCard.id).label("n"))
        .filter(
            ReviewCard.owner_id == current_user.id,
            ReviewCard.card_type == "opening",
            ReviewCard.family == family,
        )
        .group_by(ReviewCard.opening_eco)
        .order_by(func.count(ReviewCard.id).desc())
        .first()
    )
    eco = eco_row[0] if eco_row else None

    query = db.query(OpeningBook).filter(OpeningBook.family == family)
    if eco:
        query = query.filter(OpeningBook.eco == eco)

    # a linha mais longa do ECO escolhido é a "principal" para treinar
    line = query.order_by(func.length(OpeningBook.uci).desc()).first()
    if line is None:
        line = (
            db.query(OpeningBook)
            .filter(OpeningBook.family == family)
            .order_by(OpeningBook.eco.asc())
            .first()
        )
    if line is None:
        raise HTTPException(status_code=404, detail="Família não encontrada no livro.")

    uci_moves = line.uci.split()
    board = chess.Board()
    san_moves: list[str] = []
    for token in uci_moves:
        move = chess.Move.from_uci(token)
        if move not in board.legal_moves:
            break
        san_moves.append(board.san(move))
        board.push(move)

    progress = _get_or_create_progress(db, current_user.id, line.id)
    unlocked = min(progress.unlocked_plies, len(san_moves))

    return {
        "book_id": line.id,
        "eco": line.eco,
        "name": line.name,
        "family": line.family,
        "user_color": color,
        "san_moves": san_moves,
        "uci_moves": uci_moves[: len(san_moves)],
        "unlocked_plies": unlocked,
        "times_completed": progress.times_completed,
        "level_plies": LEVEL_PLIES,
    }


@router.post("/line-session/complete")
def line_session_complete(
    payload: LineCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fim de um nível: sem erros -> desbloqueia os próximos 4 plies (estilo
    Lotus); com erros -> repete o mesmo nível para fixar a memória muscular.
    """
    line = db.query(OpeningBook).filter(OpeningBook.id == payload.book_id).first()
    if line is None:
        raise HTTPException(status_code=404, detail="Linha não encontrada.")

    total_plies = len(line.uci.split())
    progress = _get_or_create_progress(db, current_user.id, line.id)
    progress.best_mistakes = min(progress.best_mistakes, payload.mistakes)

    leveled_up = False
    if payload.mistakes == 0 and progress.unlocked_plies < total_plies:
        progress.unlocked_plies = min(progress.unlocked_plies + LEVEL_PLIES, total_plies)
        leveled_up = True

    if payload.mistakes == 0:
        progress.times_completed += 1

    db.commit()

    return {
        "unlocked_plies": min(progress.unlocked_plies, total_plies),
        "total_plies": total_plies,
        "leveled_up": leveled_up,
        "times_completed": progress.times_completed,
        "best_mistakes": progress.best_mistakes,
    }


def _get_or_create_progress(db: Session, user_id: str, book_id: int) -> LineProgress:
    progress = (
        db.query(LineProgress)
        .filter(LineProgress.user_id == user_id, LineProgress.book_id == book_id)
        .first()
    )
    if progress is None:
        progress = LineProgress(
            id=str(uuid.uuid4()),
            user_id=user_id,
            book_id=book_id,
            unlocked_plies=LEVEL_PLIES,
        )
        db.add(progress)
        db.commit()
        db.refresh(progress)
    return progress


@router.post("/line-session/check")
def line_session_check(
    payload: LineMoveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Valida um lance do treino guiado com o pipeline híbrido estilo Lotus:

    1. no livro -> correto
    2. fora do livro -> filtro Stockfish (sólidas = dentro de 40cp)
    3. dica de ensino: a jogada mais jogada por humanos na posição
       (Lichess Explorer, faixa de rating do utilizador)
    4. oponente: resposta do livro OU amostrada da distribuição humana
    """
    line = db.query(OpeningBook).filter(OpeningBook.id == payload.book_id).first()
    if line is None:
        raise HTTPException(status_code=404, detail="Linha não encontrada.")

    book_uci = line.uci.split()

    # reconstrói a linha real jogada (permite desvios no modo humano)
    played_line = payload.played_uci or []
    board = chess.Board()
    on_book = True
    for i, token in enumerate(played_line):
        try:
            move = chess.Move.from_uci(token)
        except Exception:
            raise HTTPException(status_code=400, detail="Lance ilegível no histórico.")
        if move not in board.legal_moves:
            raise HTTPException(status_code=400, detail="Histórico ilegal.")
        if on_book and (i >= len(book_uci) or book_uci[i] != token):
            on_book = False
        board.push(move)

    ply = len(played_line)
    progress = _get_or_create_progress(db, current_user.id, payload.book_id)
    if ply >= progress.unlocked_plies:
        raise HTTPException(
            status_code=400,
            detail="Nível bloqueado: completa o atual sem erros para avançar.",
        )

    expected_uci = book_uci[ply] if on_book and ply < len(book_uci) else None
    book_san = None
    if expected_uci:
        try:
            book_san = board.san(chess.Move.from_uci(expected_uci))
        except Exception:
            book_san = None

    try:
        played = chess.Move.from_uci(payload.uci)
    except Exception:
        raise HTTPException(status_code=400, detail="Lance ilegível.")

    if played not in board.legal_moves:
        return {
            "status": "illegal",
            "message": "Esse lance não é legal nesta posição.",
            "best_san": book_san,
        }

    band = ratings_band_for(current_user.peak_rating)
    user_color = payload.color if payload.color in ("white", "black") else "white"

    def _tip(exclude_uci: str | None) -> str | None:
        """Passo 3: ensina a jogada prática — o que os humanos jogam aqui."""
        moves = explorer_moves(board.fen(), ratings=band)
        top = next((m for m in moves if m["uci"] != exclude_uci), None)
        if top and top["games"] >= 30:
            return (
                f"A jogada mais jogada aqui é {top['san']} — "
                f"{win_rate_for(top, user_color)}% de vitórias em "
                f"{top['games']:,} jogos da tua faixa."
            )
        return None

    def _reply(board_after_user: chess.Board, ply_now: int) -> str | None:
        """Passo 5: oponente do livro ou 'o humano típico da tua faixa'."""
        if payload.opponent != "human":
            return _next_uci(book_uci, ply_now)

        sampled = sample_human_reply(
            explorer_moves(board_after_user.fen(), ratings=band)
        )
        return sampled or _next_uci(book_uci, ply_now)

    # 1) lance do livro
    if expected_uci and payload.uci == expected_uci:
        board_after = board.copy()
        board_after.push(played)
        return {
            "status": "book",
            "message": None,
            "tip": _tip(payload.uci),
            "next_uci": _reply(board_after, ply),
        }

    # 2) fora do livro -> filtro do motor
    if played not in board.legal_moves:
        return {"status": "illegal", "message": "Lance ilegal.", "best_san": book_san}

    board_after = board.copy()
    board_after.push(played)

    if board_after.is_checkmate():
        return {
            "status": "book",
            "message": "Mate! Fora do livro, mas o motor não se queixa.",
            "tip": _tip(payload.uci),
            "next_uci": _reply(board_after, ply),
        }

    solid = solid_moves(board)
    eval_before = white_cp(board)
    eval_after = white_cp(board_after)

    if payload.uci in solid:
        return {
            "status": "engine_ok",
            "message": "Fora do livro, mas o Stockfish considera sólido. Continuamos!",
            "tip": _tip(payload.uci),
            "next_uci": _reply(board_after, ply),
        }

    user_is_white = user_color == "white"
    if eval_before is None or eval_after is None:
        message = f"Esse lance não está na teoria. Era {book_san or '?'}." if book_san else \
            "Esse lance não está na teoria."
        return {
            "status": "wrong",
            "message": message,
            "tip": _tip(payload.uci),
            "best_san": book_san,
        }

    loss = (eval_before - eval_after) if user_is_white else (eval_after - eval_before)
    best = best_move_san(board) or book_san or "?"
    message = interpret_loss(loss, board, best)
    return {
        "status": "wrong",
        "message": message,
        "tip": _tip(payload.uci),
        "best_san": best,
    }


def _board_at(uci_moves: list[str], ply: int) -> chess.Board:
    board = chess.Board()
    for token in uci_moves[:ply]:
        board.push(chess.Move.from_uci(token))
    return board


def _next_uci(uci_moves: list[str], ply: int) -> str | None:
    """Resposta do 'adversário' (a linha do livro) após o lance do jogador."""
    nxt = uci_moves[ply + 1] if ply + 1 < len(uci_moves) else None
    return nxt


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
            board = chess.Board(card.fen)
            move = chess.Move.from_uci(payload.move_uci)
            if move in board.legal_moves:
                board.push(move)
                correct = board.is_checkmate()
                board.pop()
        except Exception:
            pass

    mastery_before = card.mastery or 0

    # === mastery engine (§23-24, §27): subida consistente, queda parcial ===
    if payload.hinted and correct:
        # revelámos a resposta: recupera um pouco mas volta cedo
        card.mastery = min(100, mastery_before + 4)
        card.streak = 0
        apply_review(card, False)
        correct = True  # o lance estava certo; o agendamento é que pune
        hinted_result = True
    elif correct:
        bonus = 2 if (card.streak or 0) >= 2 else 0
        card.mastery = min(100, mastery_before + 12 + bonus)
        card.streak = (card.streak or 0) + 1
        apply_review(card, True)
        hinted_result = False
    else:
        card.mastery = max(0, mastery_before - 25)
        card.streak = 0
        card.lapses = (card.lapses or 0) + 1
        apply_review(card, False)
        hinted_result = False

    _update_streak(current_user)
    db.commit()

    message = None
    if not correct:
        try:
            from app.services import engine_service

            board = chess.Board(card.fen)
            loss = None
            if engine_service.get_engine() is not None:
                before = engine_service.white_cp(board)
                after_board = board.copy()
                after_board.push(chess.Move.from_uci(payload.move_uci))
                after = engine_service.white_cp(after_board)
                if before is not None and after is not None:
                    mover_is_white = board.turn == chess.WHITE
                    loss = (before - after) if mover_is_white else (after - before)
            best = engine_service.best_move_san(board) or card.correct_move
            message = engine_service.interpret_loss(
                loss if loss is not None else 150, board, best
            )
        except Exception:
            message = f"O melhor era {card.correct_move}."

    tip = None
    if not correct and card.card_type == "opening":
        try:
            tip = _explorer_tip(
                card.fen,
                payload.move_uci,
                card.color or "white",
                current_user.peak_rating,
            )
        except Exception:
            tip = None

    return {
        "correct": correct,
        "hinted": hinted_result,
        "correct_move": card.correct_move,
        "interval_days": card.interval_days,
        "next_review_at": card.next_review_at.isoformat(),
        "streak_days": current_user.streak_days or 0,
        "mastery": card.mastery,
        "mastery_before": mastery_before,
        "message": message,
        "tip": tip,
    }


@router.get("/browse")
def browse_repertoire(
    card_type: str | None = Query(default=None),
    family: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Vista 'Study' (a que falta ao Lotus): todo o repertório com estado,
    lance correto e contexto — para rever sem estar numa sessão.
    """
    _ensure_families(db, current_user.id)

    query = db.query(ReviewCard).filter(ReviewCard.owner_id == current_user.id)
    if card_type in ("opening", "puzzle"):
        query = query.filter(ReviewCard.card_type == card_type)
    if family:
        query = query.filter(ReviewCard.family == family)

    cards = query.order_by(
        ReviewCard.family.asc(),
        ReviewCard.occurrences.desc(),
    ).all()

    result = []
    for card in cards:
        summary = _card_summary(card)
        summary["correct_move"] = card.correct_move
        result.append(summary)
    return result


def _explorer_tip(fen: str, played_uci: str, user_color: str, peak_rating: int | None) -> str | None:
    """O 'porquê' que o Lotus não dá: win rate humano da alternativa prática."""
    from app.services.explorer_client import explorer_moves, ratings_band_for, win_rate_for

    moves = explorer_moves(fen, ratings=ratings_band_for(peak_rating))
    top = next((m for m in moves if m["uci"] != played_uci), None)
    if top and top["games"] >= 30:
        return (
            f"Curiosidade: {top['san']} é a jogada mais jogada aqui — "
            f"{win_rate_for(top, user_color)}% de vitórias em {top['games']:,} jogos."
        )
    return None


@router.post("/cards/{card_id}/hint")
def card_hint(
    card_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hint nível 1: que peça jogar (sem revelar o lance, sem penalização)."""
    card = (
        db.query(ReviewCard)
        .filter(ReviewCard.owner_id == current_user.id, ReviewCard.id == card_id)
        .first()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    san = card.correct_move or ""
    piece_map = {"N": "um cavalo", "B": "um bispo", "R": "uma torre", "Q": "a dama", "K": "o rei"}
    first = san[0] if san else ""
    if first in piece_map:
        piece = piece_map[first]
    else:
        piece = "um peão"

    # casa clara/escura de destino, quando sabemos o lance em UCI
    square_hint = ""
    if card.correct_move_uci and len(card.correct_move_uci) >= 4:
        try:
            sq = chess.SquareSet([chess.parse_square(card.correct_move_uci[2:4])]).pop()
            is_light = chess.square_color(sq) == chess.WHITE
            square_hint = "casa clara" if is_light else "casa escura"
        except Exception:
            pass

    return {"piece": piece, "square_hint": square_hint}


@router.post("/cards/{card_id}/reveal")
def card_reveal(
    card_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hint nível 3: revela o lance. Não pontua aqui — o frontend marca a
    resposta seguinte como 'hinted', que volta mais cedo no agendamento."""
    card = (
        db.query(ReviewCard)
        .filter(ReviewCard.owner_id == current_user.id, ReviewCard.id == card_id)
        .first()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    return {"correct_move": card.correct_move}


def _update_streak(user: User) -> None:
    today = date.today()
    if user.last_trained_date == today:
        return
    if user.last_trained_date == today - timedelta(days=1):
        user.streak_days = (user.streak_days or 0) + 1
    else:
        user.streak_days = 1
    user.last_trained_date = today


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

    return {
        "opening": counts("opening"),
        "puzzle": counts("puzzle"),
        "streak_days": current_user.streak_days or 0,
    }
