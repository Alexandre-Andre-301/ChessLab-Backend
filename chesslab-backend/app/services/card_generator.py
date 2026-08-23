import io
from collections import Counter

import chess
import chess.pgn

from app.models.game import Game
from app.models.review_card import ReviewCard

MAX_OPENING_CARDS = 60
MAX_PUZZLE_CARDS = 30
MAX_OPENING_PLY = 12          # só os primeiros 6 lances de cada lado
MIN_SEE_GAIN_CP = 150         # captura tem de ganhar >= 1.5 peões de material
MAX_GAMES_SCANNED = 200

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 310,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

GAMBIT_RESULTS = {"accepted", "declined", "refused"}


def fen_key(board: chess.Board) -> str:
    """FEN normalizado (sem contadores de lances) para dedupe estável."""
    return " ".join(board.fen().split()[:4])


def see_capture(board: chess.Board, move: chess.Move) -> int:
    """
    Static Exchange Evaluation simplificado: simula as trocas na casa de
    destino (ambos capturam sempre com a peça mais barata disponível).
    Devolve o material líquido ganho em centipeões.
    """
    if not board.is_capture(move):
        return 0

    gains = [PIECE_VALUES.get(board.piece_type_at(move.to_square), 0)]

    simulated = board.copy()
    simulated.push(move)

    while True:
        attackers = simulated.attackers(simulated.turn, move.to_square) & simulated.occupied
        if not attackers:
            break

        cheapest_sq = min(
            attackers,
            key=lambda sq: PIECE_VALUES.get(simulated.piece_type_at(sq), 0),
        )
        gains.append(PIECE_VALUES.get(simulated.piece_type_at(cheapest_sq), 0))
        simulated.push(chess.Move(cheapest_sq, move.to_square))

    score = 0
    for gain in reversed(gains):
        score = gain - score
    return score


def find_puzzles_in_game(pgn_text: str, player_color: chess.Color) -> list[tuple[str, str, str]]:
    """
    Percorre o PGN e devolve puzzles [(fen_key, san, uci)] nas posições em
    que era a vez do jogador e existia mate em 1 ou captura vencedora.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return []

    found: list[tuple[str, str, str]] = []
    seen_in_game: set[str] = set()

    node = game
    board = game.board()

    while node.variations and len(found) < 2:
        move = node.variations[0].move
        if move is None:
            break

        if board.turn == player_color and not board.is_game_over():
            best_san, best_uci, best_gain = "", "", MIN_SEE_GAIN_CP - 1

            for candidate in board.legal_moves:
                is_mate = _is_mate_in_one(board, candidate)
                if is_mate:
                    best_san, best_uci, best_gain = (
                        board.san(candidate),
                        candidate.uci(),
                        10_000,
                    )
                    break

                gain = see_capture(board, candidate)
                if gain > best_gain:
                    best_gain = gain
                    best_san = board.san(candidate)
                    best_uci = candidate.uci()

            if best_uci:
                key = fen_key(board)
                if key not in seen_in_game:
                    seen_in_game.add(key)
                    found.append((key, best_san, best_uci))

        board.push(move)
        node = node.variations[0]

    return found


def _is_mate_in_one(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    is_mate = board.is_checkmate()
    board.pop()
    return is_mate


def generate_cards(db, user) -> dict:
    """
    Cria cartões SR a partir dos jogos já importados do utilizador:
    - aberturas: lances do próprio jogador nos primeiros plies (voto por maioria)
    - puzzles: mate em 1 / capturas vencedoras nas posições dele
    """
    existing_keys = {
        (fen, card_type)
        for fen, card_type in db.query(ReviewCard.fen, ReviewCard.card_type)
        .filter(ReviewCard.owner_id == user.id)
        .all()
    }

    games = (
        db.query(Game)
        .filter(Game.owner_id == user.id, Game.pgn != "")
        .order_by(Game.played_at.desc())
        .limit(MAX_GAMES_SCANNED)
        .all()
    )

    username = (user.chesscom_username or "").lower()
    opening_votes: Counter = Counter()          # (fen, eco) -> Counter[(san, uci)]
    puzzle_candidates: list[tuple[str, str, str, str | None]] = []

    for game in games:
        try:
            parsed = chess.pgn.read_game(io.StringIO(game.pgn))
            if parsed is None:
                continue

            color = _resolve_player_color(parsed, username, game.color)
            if color is None:
                continue

            # ---- cartões de abertura ----
            node = parsed
            board = parsed.board()
            ply = 0
            while node.variations and ply < MAX_OPENING_PLY:
                move = node.variations[0].move
                if move is None:
                    break

                if board.turn == color:
                    bucket = opening_votes.setdefault(
                        (fen_key(board), game.opening_eco), Counter()
                    )
                    bucket[(board.san(move), move.uci())] += 1

                board.push(move)
                node = node.variations[0]
                ply += 1

            # ---- puzzles ----
            if len(puzzle_candidates) < MAX_PUZZLE_CARDS:
                for fen, san, uci in find_puzzles_in_game(game.pgn, color):
                    puzzle_candidates.append((fen, san, uci, game.opening_eco))
                    if len(puzzle_candidates) >= MAX_PUZZLE_CARDS:
                        break
        except Exception:
            # um PGN problemático não pode rebentar a geração toda
            continue

    openings_created = _create_opening_cards(db, user.id, opening_votes, existing_keys)
    puzzles_created = _create_puzzle_cards(db, user.id, puzzle_candidates, existing_keys)
    db.commit()

    return {"opening_cards": openings_created, "puzzle_cards": puzzles_created}


def _create_opening_cards(db, user_id, votes: Counter, existing_keys) -> int:
    created = 0

    # voto por maioria: o lance mais jogado pelo próprio é "o repertório"
    best_by_fen: dict[str, tuple[str, str, str | None]] = {}
    for (fen, eco), choices in votes.items():
        (san, uci), count = choices.most_common(1)[0]
        current = best_by_fen.get(fen)
        if current is None or count > 0:
            if current is None or choices[(current[0], current[1])] < count:
                best_by_fen[fen] = (san, uci, eco)

    for fen, (san, uci, eco) in best_by_fen.items():
        if created >= MAX_OPENING_CARDS:
            break
        if (fen, "opening") in existing_keys:
            continue
        db.add(
            ReviewCard(
                owner_id=user_id,
                card_type="opening",
                fen=fen,
                correct_move=san,
                correct_move_uci=uci,
                opening_eco=eco,
            )
        )
        existing_keys.add((fen, "opening"))
        created += 1

    return created


def _create_puzzle_cards(db, user_id, candidates, existing_keys) -> int:
    created = 0
    seen: set[str] = set()

    for fen, san, uci, eco in candidates:
        if created >= MAX_PUZZLE_CARDS:
            break
        if fen in seen or (fen, "puzzle") in existing_keys:
            continue
        seen.add(fen)
        db.add(
            ReviewCard(
                owner_id=user_id,
                card_type="puzzle",
                fen=fen,
                correct_move=san,
                correct_move_uci=uci,
                opening_eco=eco,
            )
        )
        existing_keys.add((fen, "puzzle"))
        created += 1

    return created


def _resolve_player_color(parsed, username: str, stored_color: str | None) -> chess.Color | None:
    """Descobre a cor do jogador pelos headers do PGN (fallback: coluna color)."""
    white = parsed.headers.get("White", "").strip().lower()
    black = parsed.headers.get("Black", "").strip().lower()

    if username and username in (white, black):
        return chess.WHITE if username == white else chess.BLACK

    if stored_color == "white":
        return chess.WHITE
    if stored_color == "black":
        return chess.BLACK

    return None
