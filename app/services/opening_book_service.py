import io
import re

import chess
import httpx
from sqlalchemy.orm import Session

from app.models.opening_book import OpeningBook
from app.services.analytics import opening_family

BOOK_BASE_URL = "https://raw.githubusercontent.com/lichess-org/chess-openings/master"
FILES = ["a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv"]

HEADERS = {"User-Agent": "ChessLab/0.1 (opening book sync)"}

MOVE_NUMBER_RE = re.compile(r"\d+\.(\.\.)?")
RESULT_RE = re.compile(r"(1-0|0-1|1/2-1/2|\*)")


def derive_uci_epd(pgn_moves: str) -> tuple[str | None, str | None]:
    """Converte a coluna pgn (SAN) em linha UCI + EPD da posição final."""
    cleaned = RESULT_RE.sub(" ", MOVE_NUMBER_RE.sub(" ", pgn_moves))
    board = chess.Board()
    ucis: list[str] = []

    for token in cleaned.split():
        try:
            move = board.parse_san(token)
        except Exception:
            return None, None
        ucis.append(move.uci())
        board.push(move)

    if not ucis:
        return None, None
    return " ".join(ucis), board.epd()


def book_family(name: str) -> str:
    """O dataset usa 'Sicilian Defense: Najdorf Variation' — família antes dos ':'."""
    if ":" in name:
        return name.split(":", 1)[0].strip()
    return opening_family(name) or name.strip()


def sync_book(db: Session) -> int:
    """Descarrega a base ECO do Lichess e faz upsert por EPD."""
    existing_epds = {row for (row,) in db.query(OpeningBook.epd).all()}

    for file_name in FILES:
        response = httpx.get(f"{BOOK_BASE_URL}/{file_name}", headers=HEADERS, timeout=30)
        response.raise_for_status()

        reader = io.StringIO(response.text)
        header = reader.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}

        pending: list[OpeningBook] = []
        for raw_line in reader:
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) < len(header):
                continue

            eco = parts[idx["eco"]].strip()
            name = parts[idx["name"]].strip()

            uci, epd = derive_uci_epd(parts[idx["pgn"]])
            if not uci or not epd or epd in existing_epds:
                continue

            existing_epds.add(epd)
            pending.append(
                OpeningBook(
                    eco=eco,
                    name=name,
                    family=book_family(name),
                    uci=uci,
                    epd=epd,
                )
            )

        db.add_all(pending)
        db.commit()

    return db.query(OpeningBook).count()


def ensure_synced(db: Session) -> None:
    """Sincroniza a base uma única vez, sem rebentar o arranque se offline."""
    try:
        if db.query(OpeningBook).count() == 0:
            sync_book(db)
    except Exception:
        db.rollback()


def get_lines_by_family(db: Session, family: str, limit: int = 6) -> list[OpeningBook]:
    return (
        db.query(OpeningBook)
        .filter(OpeningBook.family == family)
        .order_by(OpeningBook.eco.asc(), OpeningBook.id.asc())
        .limit(limit)
        .all()
    )


def family_for_eco(db: Session, eco: str | None) -> str | None:
    if not eco:
        return None
    row = db.query(OpeningBook.family).filter(OpeningBook.eco == eco).first()
    return row[0] if row else None
