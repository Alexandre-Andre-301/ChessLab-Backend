from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# check_same_thread=False é necessário só pro SQLite (por causa do FastAPI
# poder usar múltiplas threads); não faz nada em Postgres se migrares depois
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency do FastAPI: abre sessão, entrega, fecha sempre no fim."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
