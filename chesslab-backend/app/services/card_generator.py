import io
from collections import Counter

import chess
import chess.pgn
from sqlalchemy import text

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


def _piece_name(piece_type: int) -> str:
    names = {
        chess.PAWN: "peão",
        chess.KNIGHT: "cavalo",
        chess.BISHOP: "bispo",
        chess.ROOK: "torre",
        chess.QUEEN: "dama",
    }
    return names.get(piece_type, "peça")


def find_puzzles_in_game(
    pgn_text: str, player_color: chess.Color
) -> list[tuple[str, str, str, list[str], str]]:
    """
    Percorre o PGN e devolve puzzles:
    [(fen_key, san, uci, linha_san_ate_posicao, explicacao)]
    nas posições em que era a vez do jogador e existia mate em 1 ou
    captura vencedora.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return []

    found: list[tuple[str, str, str, list[str], str]] = []
    seen_in_game: set[str] = set()

    node = game
    board = game.board()
    line: list[str] = []

    while node.variations and len(found) < 2:
        move = node.variations[0].move
        if move is None:
            break

        if board.turn == player_color and not board.is_game_over():
            best_san, best_uci, best_gain = "", "", MIN_SEE_GAIN_CP - 1
            best_captured: int | None = None

            for candidate in board.legal_moves:
                if _is_mate_in_one(board, candidate):
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
                    best_captured = board.piece_type_at(candidate.to_square)

            if best_uci:
                key = fen_key(board)
                if key not in seen_in_game:
                    seen_in_game.add(key)

                    if best_gain >= 10_000:
                        explanation = "Há mate em 1 nesta posição. Encontra o lance."
                    elif best_captured is not None:
                        explanation = (
                            f"Podes capturar {_article(best_captured)} e ganhar ~"
                            f"{best_gain / 100:.1f} peças de material na troca."
                        )
                    else:
                        explanation = "Existe um lance que ganha material."

                    found.append((key, best_san, best_uci, list(line), explanation))

        san = board.san(move)
        board.push(move)
        line.append(san)
        node = node.variations[0]

    return found


def _article(piece_type: int) -> str:
    names = {
        chess.PAWN: "um peão",
        chess.KNIGHT: "um cavalo",
        chess.BISHOP: "um bispo",
        chess.ROOK: "uma torre",
        chess.QUEEN: "a dama",
    }
    return names.get(piece_type, "material")


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
    Cada cartão guarda contexto estilo Lotus: frequência, linha até à posição
    e explicação do porquê do lance.
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

    # (fen, eco) -> {"moves": Counter[(san, uci)], "line": [...], "count": n}
    opening_positions: dict[tuple[str, str | None], dict] = {}
    puzzle_candidates: list[tuple[str, str, str, list[str], str, str | None]] = []

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
            line: list[str] = []
            ply = 0
            while node.variations and ply < MAX_OPENING_PLY:
                move = node.variations[0].move
                if move is None:
                    break

                if board.turn == color:
                    entry = opening_positions.setdefault(
                        (fen_key(board), game.opening_eco),
                        {"moves": Counter(), "line": [], "count": 0},
                    )
                    entry["moves"][(board.san(move), move.uci())] += 1
                    entry["count"] += 1
                    # guarda a linha mais curta que chega a esta posição
                    if not entry["line"] or len(line) < len(entry["line"]):
                        entry["line"] = list(line)

                san = board.san(move)
                board.push(move)
                line.append(san)
                node = node.variations[0]
                ply += 1

            # ---- puzzles ----
            if len(puzzle_candidates) < MAX_PUZZLE_CARDS:
                for fen, san, uci, puzzle_line, explanation in find_puzzles_in_game(
                    game.pgn, color
                ):
                    puzzle_candidates.append(
                        (fen, san, uci, puzzle_line, explanation, game.opening_eco)
                    )
                    if len(puzzle_candidates) >= MAX_PUZZLE_CARDS:
                        break
        except Exception:
            # um PGN problemático não pode rebentar a geração toda
            continue

    openings_created = _create_opening_cards(
        db, user.id, opening_positions, existing_keys
    )
    puzzles_created = _create_puzzle_cards(db, user.id, puzzle_candidates, existing_keys)
    db.commit()

    return {"opening_cards": openings_created, "puzzle_cards": puzzles_created}


def _family_for_eco(db, eco: str | None) -> str | None:
    """Procura a família na base ECO do Lichess; fallback: prefixo do código."""
    if not eco:
        return None
    row = db.execute(
        text("SELECT family FROM opening_book WHERE eco = :eco LIMIT 1"),
        {"eco": eco},
    ).first()
    return row[0] if row else None


def _create_opening_cards(db, user_id, positions: dict, existing_keys) -> int:
    created = 0

    # agrega por fen: soma ocorrências e guarda o lance mais votado
    by_fen: dict[str, dict] = {}
    for (fen, eco), entry in positions.items():
        target = by_fen.setdefault(
            fen, {"occurrences": 0, "best": None, "best_count": -1, "eco": eco}
        )
        target["occurrences"] += entry["count"]
        (san, uci), count = entry["moves"].most_common(1)[0]
        if count > target["best_count"]:
            target["best_count"] = count
            target["best"] = (san, uci, entry["line"])

    for fen, data in sorted(
        by_fen.items(), key=lambda kv: kv[1]["occurrences"], reverse=True
    ):
        if created >= MAX_OPENING_CARDS:
            break
        if (fen, "opening") in existing_keys:
            continue

        san, uci, line = data["best"]
        eco = data["eco"]
        color = "white" if fen.split()[1] == "w" else "black"

        db.add(
            ReviewCard(
                owner_id=user_id,
                card_type="opening",
                fen=fen,
                correct_move=san,
                correct_move_uci=uci,
                opening_eco=eco,
                family=_family_for_eco(db, eco),
                color=color,
                occurrences=data["occurrences"],
                line_moves=" ".join(line),
            )
        )
        existing_keys.add((fen, "opening"))
        created += 1

    return created


def _create_puzzle_cards(db, user_id, candidates, existing_keys) -> int:
    created = 0
    seen: set[str] = set()

    for fen, san, uci, line, explanation, eco in candidates:
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
                family=_family_for_eco(db, eco),
                color="white" if fen.split()[1] == "w" else "black",
                occurrences=1,
                line_moves=" ".join(line),
                explanation=explanation,
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
