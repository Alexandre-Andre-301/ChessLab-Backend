from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint

from app.database import Base


class LineProgress(Base):
    """
    Progresso do utilizador numa linha teórica do livro ECO (estilo Lotus):
    começa com os primeiros 4 plies desbloqueados e vai ganhando profundidade
    à medida que completa níveis sem erros.
    """
    __tablename__ = "line_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_line_progress_user_book"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    book_id = Column(Integer, nullable=False, index=True)

    unlocked_plies = Column(Integer, nullable=False, default=4)
    times_completed = Column(Integer, nullable=False, default=0)
    best_mistakes = Column(Integer, nullable=False, default=99)
