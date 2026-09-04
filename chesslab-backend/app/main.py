from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.database import Base, SessionLocal, engine
from app.routers import auth, users, games, sync, training, insights, openings
from app.services import opening_book_service

# cria as tabelas no SQLite se ainda não existirem.
# Nota: isto serve pro MVP. Quando o schema começar a mudar com frequência,
# vale a pena migrar pra Alembic (migrações versionadas) em vez disto.
Base.metadata.create_all(bind=engine)


def run_dev_migrations() -> None:
    """Adiciona colunas novas à tabela users numa BD já existente.

    Enquanto não há Alembic, isto mantém a BD de desenvolvimento atualizada
    sem ter de apagar o chesslab.db.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "main_goal" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN main_goal VARCHAR"))
        if "peak_rating" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN peak_rating INTEGER"))
        if "onboarding_completed" not in existing:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT 0")
            )
        if "streak_days" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN streak_days INTEGER DEFAULT 0"))
        if "last_trained_date" not in existing:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_trained_date DATE"))

    if "games" in inspector.get_table_names():
        with engine.begin() as conn:
            # BD antigas tinham chesscom_game_id único GLOBAL, o que impedia
            # duas contas de importar jogos do mesmo jogador
            try:
                conn.execute(text("DROP INDEX IF EXISTS ix_games_chesscom_game_id"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_games_owner_game "
                        "ON games (owner_id, chesscom_game_id)"
                    )
                )
            except Exception:
                pass

    if "review_cards" in inspector.get_table_names():
        existing_rc = {col["name"] for col in inspector.get_columns("review_cards")}
        with engine.begin() as conn:
            if "card_type" not in existing_rc:
                conn.execute(
                    text("ALTER TABLE review_cards ADD COLUMN card_type VARCHAR DEFAULT 'opening'")
                )
            if "correct_move_uci" not in existing_rc:
                conn.execute(
                    text("ALTER TABLE review_cards ADD COLUMN correct_move_uci VARCHAR")
                )
            if "occurrences" not in existing_rc:
                conn.execute(
                    text("ALTER TABLE review_cards ADD COLUMN occurrences INTEGER DEFAULT 1")
                )
            if "line_moves" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN line_moves TEXT"))
            if "explanation" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN explanation TEXT"))
            if "family" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN family VARCHAR"))
            if "color" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN color VARCHAR"))
            if "mastery" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN mastery INTEGER DEFAULT 0"))
            if "streak" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN streak INTEGER DEFAULT 0"))
            if "lapses" not in existing_rc:
                conn.execute(text("ALTER TABLE review_cards ADD COLUMN lapses INTEGER DEFAULT 0"))


run_dev_migrations()

app = FastAPI(title="ChessLab API", version="0.1.0")

import os
from fastapi.middleware.cors import CORSMiddleware

# Origins permitidas: localhost p/ dev + Vercel preview/production
frontend_url = os.getenv(
    "FRONTEND_URL",
    "https://chesslab-frontend01-one.vercel.app"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(games.router)
app.include_router(sync.router)
app.include_router(training.router)
app.include_router(insights.router)
app.include_router(openings.router)


# sincroniza a base de aberturas do Lichess na primeira arranque
def bootstrap_opening_book() -> None:
    db = SessionLocal()
    try:
        opening_book_service.ensure_synced(db)
    finally:
        db.close()


try:
    bootstrap_opening_book()
except Exception:
    pass


@app.get("/")
def root():
    return {"status": "ChessLab API a correr"}
