import io
from datetime import datetime

import chess.pgn


def extract_game_id(chesscom_url: str) -> str:
    """A URL do Chess.com termina com o ID único da partida."""
    return chesscom_url.rstrip("/").split("/")[-1]


def parse_opening_from_pgn(pgn_text: str) -> tuple[str | None, str | None]:
    """
    Extrai o ECO code e o nome da abertura dos headers do PGN.
    O Chess.com normalmente inclui [ECO "..."] e [ECOUrl "..."].
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None, None

    eco = game.headers.get("ECO")
    eco_url = game.headers.get("ECOUrl", "")

    # ECOUrl costuma ser tipo: https://www.chess.com/openings/Sicilian-Defense
    # extraímos um nome legível a partir disso
    opening_name = None
    if eco_url:
        slug = eco_url.rstrip("/").split("/")[-1]
        opening_name = slug.replace("-", " ")

    return eco, opening_name


def parse_game(raw_game: dict, chesscom_username: str) -> dict:
    """
    Recebe um objeto de partida como devolvido pela PubAPI do Chess.com
    e devolve um dict pronto a virar um model Game.
    """
    pgn_text = raw_game.get("pgn", "")
    eco, opening_name = parse_opening_from_pgn(pgn_text)

    white = raw_game.get("white", {})
    black = raw_game.get("black", {})

    is_white = white.get("username", "").lower() == chesscom_username.lower()
    player_side = white if is_white else black
    opponent_side = black if is_white else white

    # Chess.com devolve "win", "checkmated", "resigned", "timeout", etc.
    # Normalizamos pra win/loss/draw do ponto de vista do jogador.
    raw_result = player_side.get("result", "")
    if raw_result == "win":
        result = "win"
    elif raw_result in ("agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"):
        result = "draw"
    else:
        result = "loss"

    played_at = None
    if raw_game.get("end_time"):
        played_at = datetime.utcfromtimestamp(raw_game["end_time"])

    return {
        "chesscom_game_id": extract_game_id(raw_game.get("url", "")),
        "pgn": pgn_text,
        "time_class": raw_game.get("time_class"),
        "color": "white" if is_white else "black",
        "result": result,
        "opening_eco": eco,
        "opening_name": opening_name,
        "player_rating": player_side.get("rating"),
        "opponent_rating": opponent_side.get("rating"),
        "opponent_username": opponent_side.get("username"),
        "played_at": played_at,
    }
