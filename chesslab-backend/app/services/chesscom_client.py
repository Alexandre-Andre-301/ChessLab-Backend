import httpx

from app.config import settings

# A PubAPI do Chess.com exige um User-Agent identificável, senão às vezes
# devolve 403. Não precisa de API key nem autenticação (é tudo público).
HEADERS = {"User-Agent": "ChessLab/0.1 (contact: your-email@example.com)"}


class ChessComError(Exception):
    pass


def get_player_profile(username: str) -> dict:
    """Devolve o perfil público do jogador (usado para validar usernames)."""
    url = f"{settings.chesscom_base_url}/player/{username}"
    response = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)

    if response.status_code == 404:
        raise ChessComError(f"Username '{username}' não encontrado no Chess.com")
    response.raise_for_status()

    return response.json()


def get_archives(username: str) -> list[str]:
    """Devolve lista de URLs, uma por mês, com o histórico do jogador."""
    url = f"{settings.chesscom_base_url}/player/{username}/games/archives"
    response = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)

    if response.status_code == 404:
        raise ChessComError(f"Username '{username}' não encontrado no Chess.com")
    response.raise_for_status()

    return response.json().get("archives", [])


def get_games_from_archive(archive_url: str) -> list[dict]:
    """Devolve a lista de partidas (já em JSON, com PGN incluído) de um mês."""
    response = httpx.get(archive_url, headers=HEADERS, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response.json().get("games", [])


def get_all_games(username: str, limit_months: int | None = None) -> list[dict]:
    """
    Junta as partidas de todos os arquivos mensais.
    limit_months: útil pra importar só os meses mais recentes.
    """
    archives = get_archives(username)
    if limit_months:
        archives = archives[-limit_months:]

    all_games = []
    for archive_url in archives:
        all_games.extend(get_games_from_archive(archive_url))

    return all_games
