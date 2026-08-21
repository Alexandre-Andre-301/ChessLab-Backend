from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth, users, games, sync

# cria as tabelas no SQLite se ainda não existirem.
# Nota: isto serve pro MVP. Quando o schema começar a mudar com frequência,
# vale a pena migrar pra Alembic (migrações versionadas) em vez disto.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="ChessLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # porta padrão do Vite
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(games.router)
app.include_router(sync.router)


@app.get("/")
def root():
    return {"status": "ChessLab API a correr"}
