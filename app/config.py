from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SQLite: arquivo local, zero configuração de servidor
    database_url: str = "sqlite:///./chesslab.db"

    # JWT
    secret_key: str = "change-me-in-.env"  # nunca deixar isto em produção
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 dias

    # Chess.com API
    chesscom_base_url: str = "https://api.chess.com/pub"

    # Lichess Opening Explorer (estatística humana; pode sobrepor-se no .env
    # se o ambiente bloquear o domínio — respostas 401 degradam sem rebentar)
    explorer_base_url: str = "https://explorer.lichess.ovh"

    class Config:
        env_file = ".env"


settings = Settings()
