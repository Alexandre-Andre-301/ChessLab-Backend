from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL: Supabase - lida com URL completa via env
    database_url: str

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 dias

    # Chess.com API
    chesscom_base_url: str = "https://api.chess.com/pub"

    # Lichess Opening Explorer
    explorer_base_url: str = "https://explorer.lichess.ovh"

    class Config:
        env_file = ".env"


settings = Settings()