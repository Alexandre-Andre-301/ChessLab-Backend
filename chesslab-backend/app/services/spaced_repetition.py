from datetime import datetime, timedelta, timezone

from app.models.review_card import ReviewCard

# intervalos do SM-2 simplificado (como o Anki)
FIRST_INTERVAL = 1
SECOND_INTERVAL = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def apply_review(card: ReviewCard, correct: bool) -> ReviewCard:
    """Atualiza o estado SR do card conforme a resposta do jogador."""
    if correct:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = FIRST_INTERVAL
        elif card.repetitions == 2:
            card.interval_days = SECOND_INTERVAL
        else:
            card.interval_days = max(1, round(card.interval_days * card.ease_factor))
        card.ease_factor = min(2.8, card.ease_factor + 0.05)
    else:
        card.repetitions = 0
        card.interval_days = 0
        card.ease_factor = max(1.3, card.ease_factor - 0.2)

    card.next_review_at = _utcnow() + timedelta(days=card.interval_days)
    card.last_reviewed_at = _utcnow()
    return card
