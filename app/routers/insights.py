from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.game import InsightItem
from app.services.analytics import build_insights, get_opening_stats
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=list[InsightItem])
def insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Insights por regras sobre dados reais do jogador:
    abertura mais fraca/forte, ritmo mais fraco, diferença entre cores.
    """
    return build_insights(db, current_user.id, current_user.chesscom_username)
