import os

import chess
import chess.engine

# margem (em centipeões) abaixo da qual um lance fora do livro continua aprovado
ENGINE_APPROVE_CP = 40
ENGINE_DEPTH = 12

_ENGINE: chess.engine.SimpleEngine | None = None
_ENGINE_TRIED = False


def _candidate_paths() -> list[str]:
    env = os.environ.get("STOCKFISH_PATH")
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "engines")
    base = os.path.normpath(base)

    candidates = []
    if env:
        candidates.append(env)

    for root, _dirs, files in os.walk(base):
        for file in files:
            if file.lower().startswith("stockfish") and file.lower().endswith(".exe"):
                candidates.append(os.path.join(root, file))

    candidates += ["/usr/bin/stockfish", "/usr/local/bin/stockfish"]
    return candidates


def get_engine() -> chess.engine.SimpleEngine | None:
    """Devolve o motor UCI se existir; caso contrário None (features degradam)."""
    global _ENGINE, _ENGINE_TRIED

    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_TRIED:
        return None

    _ENGINE_TRIED = True
    for path in _candidate_paths():
        try:
            engine = chess.engine.SimpleEngine.popen_uci(path)
            engine.configure({"Threads": 2, "Hash": 128})
            _ENGINE = engine
            return _ENGINE
        except Exception:
            continue

    return None


def white_cp(board: chess.Board, depth: int = ENGINE_DEPTH) -> int | None:
    """Avaliação em centipeões (perspetiva das brancas); mate -> ±10000."""
    engine = get_engine()
    if engine is None:
        return None

    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    score = info["score"].white()
    return score.score(mate_score=10_000)


def solid_moves(
    board: chess.Board,
    threshold_cp: int = 40,
    multipv: int = 5,
    depth: int = 12,
) -> set[str]:
    """
    Passo 2 do algoritmo Lotus: as jogadas 'sólidas' — dentro do threshold
    de centipeões da melhor, segundo o Stockfish. Evita recomendar lixo
    posicional que só ganhou por acaso na estatística.
    """
    engine = get_engine()
    if engine is None:
        return set()

    try:
        infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
    except Exception:
        return set()

    if not isinstance(infos, list):
        infos = [infos]

    scored: list[tuple[str, int]] = []
    for info in infos:
        pv = info.get("pv")
        score = info.get("score")
        if not pv or score is None:
            continue
        cp = score.pov(board.turn).score(mate_score=10_000)
        scored.append((pv[0].uci(), cp))

    if not scored:
        return set()

    best_cp = max(cp for _uci, cp in scored)
    return {uci for uci, cp in scored if best_cp - cp <= threshold_cp}


def best_move_san(board: chess.Board, depth: int = ENGINE_DEPTH) -> str | None:
    engine = get_engine()
    if engine is None:
        return None

    result = engine.play(board, chess.engine.Limit(depth=depth))
    if result.move is None:
        return None
    return board.san(result.move)


def interpret_loss(loss_cp: int, board_before: chess.Board, best_san: str | None) -> str:
    """
    Interpretador do motor: converte a perda de avaliação numa mensagem
    humana. Só é chamado quando o jogador erra — em cima não se explica.
    """
    if loss_cp >= 10_000:
        return f"Isso permitia mate. O melhor era {best_san}."

    pawns = loss_cp / 100
    parts: list[str] = []

    if loss_cp >= 300:
        parts.append(f"Lance muito duro — perdes ~{pawns:.1f} peões de vantagem.")
    elif loss_cp >= 150:
        parts.append(f"Erro: perdes ~{pawns:.1f} peões de vantagem.")
    else:
        parts.append("Quase sem custo, mas não é o que a teoria pede.")

    # pistas concretas sobre o que escapou
    if best_san:
        try:
            best = board_before.parse_san(best_san)
            if board_before.is_capture(best):
                captured = board_before.piece_type_at(best.to_square)
                names = {
                    chess.PAWN: "um peão",
                    chess.KNIGHT: "um cavalo",
                    chess.BISHOP: "um bispo",
                    chess.ROOK: "uma torre",
                    chess.QUEEN: "a dama",
                }
                if captured:
                    parts.append(f"Escapava capturar {names.get(captured, 'material')}.")
            board_before.push(best)
            if board_before.is_checkmate():
                parts.append("Havia mate!")
            board_before.pop()
        except Exception:
            pass

    if best_san:
        parts.append(f"A teoria era {best_san}.")
    return " ".join(parts)
