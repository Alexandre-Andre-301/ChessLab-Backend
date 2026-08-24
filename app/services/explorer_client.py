import random
import time

import chess
import httpx

from app.config import settings

EXPLORER_URL = None  # usado via _explorer_url() (settings.explorer_base_url)
HEADERS = {"User-Agent": "ChessLab/0.1 (move advice)"}

CACHE: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 60 * 60          # 1h
CACHE_MAX = 500


def _explorer_url() -> str:
    return f"{settings.explorer_base_url}/lichess"


def explorer_moves(
    fen: str,
    speeds: str = "blitz,rapid",
    ratings: str = "1200,1400,1600",
) -> list[dict]:
    """
    Distribuição real de jogadas humanas numa posição, via Lichess Explorer.
    Devolve [{uci, san, games, white, draws, black, avg_rating}] ordenado
    por frequência. Com cache em memória.
    """
    key = f"{fen}|{speeds}|{ratings}"
    cached = CACHE.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    try:
        response = httpx.get(
            _explorer_url(),
            params={"variant": "standard", "speeds": speeds, "ratings": ratings, "fen": fen},
            headers=HEADERS,
            timeout=6,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    data = response.json()
    total = data.get("total", 0)
    moves: list[dict] = []

    for move in data.get("moves", [])[:12]:
        san = move.get("san")
        if not san:
            continue
        try:
            uci = chess.Board(fen).parse_san(san).uci()
        except Exception:
            continue

        white = move.get("white", 0)
        draws = move.get("draws", 0)
        black = move.get("black", 0)
        games = white + draws + black

        moves.append({
            "uci": uci,
            "san": san,
            "games": games,
            "white": white,
            "draws": draws,
            "black": black,
            "avg_rating": move.get("averageRating"),
        })

    if len(CACHE) >= CACHE_MAX:
        CACHE.clear()
    CACHE[key] = (time.time(), moves)
    return moves


def win_rate_for(move: dict, user_color: str) -> float:
    if user_color == "white":
        wins = move["white"]
    else:
        wins = move["black"]
    return round((wins / move["games"]) * 100, 1) if move["games"] else 0.0


def sample_human_reply(moves: list[dict], exclude_uci: str | None = None) -> str | None:
    """Amostra a resposta do 'oponente típico' ponderada pela frequência real."""
    candidates = [m for m in moves if m["uci"] != exclude_uci and m["games"] > 0]
    if not candidates:
        return None

    total = sum(m["games"] for m in candidates)
    r = random.uniform(0, total)
    acc = 0.0
    for move in candidates:
        acc += move["games"]
        if r <= acc:
            return move["uci"]
    return candidates[-1]["uci"]


def ratings_band_for(user_rating: int | None) -> str:
    """Escolhe a faixa do explorer mais próxima do rating do utilizador."""
    bands = [1000, 1200, 1400, 1600, 1800, 2000]
    if user_rating is None:
        return "1200,1400,1600"
    center = min(bands, key=lambda b: abs(b - user_rating))
    return f"{center},{center + 200}"
