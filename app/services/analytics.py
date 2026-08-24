import chess
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models.game import Game
from app.schemas.game import OpeningStat, TimeClassStat

# palavras que marcam onde acaba o nome da família e começam as variantes
# ex.: "Caro Kann Defense 2.Nf3 d5 3.d3" -> família "Caro Kann Defense"
FAMILY_MARKERS = {
    "game",
    "opening",
    "defense",
    "defence",
    "attack",
    "gambit",
    "countergambit",
    "counter-gambit",
    "system",
    "variation",
    "accepted",
    "declined",
    "refused",
}

GAMBIT_CONTINUATIONS = {"accepted", "declined", "refused"}

MIN_GAMES_FOR_INSIGHT = 5


def _stem(token: str) -> str:
    return token.split(".")[0].strip(",").lower()


def opening_family(name: str | None) -> str | None:
    """Reduz 'Ruy Lopez Opening Morphy Defense Closed Variation...' a 'Ruy Lopez Opening'."""
    if not name:
        return None

    tokens = name.split()
    family: list[str] = []

    for i, token in enumerate(tokens):
        stem = _stem(token)

        if i > 0 and stem in FAMILY_MARKERS:
            family.append(token)

            # "Gambit Accepted/Declined/Refused" faz parte da família,
            # não é uma variante à parte
            if stem == "gambit" and i + 1 < len(tokens):
                nxt = _stem(tokens[i + 1])
                if nxt in GAMBIT_CONTINUATIONS:
                    family.append(tokens[i + 1])
            break

        family.append(token)

    return " ".join(family)


def get_opening_stats(
    db: Session,
    owner_id: str,
    time_class: str | None = None,
) -> list[OpeningStat]:
    """
    Agrupa variantes pela família (todas as Caro-Kann contam como Caro-Kann)
    e devolve win rate ordenado do pior pro melhor.
    """
    query = db.query(
        Game.opening_eco,
        Game.opening_name,
        Game.result,
    ).filter(
        Game.owner_id == owner_id,
        Game.opening_eco.isnot(None),
    )

    if time_class:
        query = query.filter(Game.time_class == time_class)

    agg: dict[str, dict[str, int]] = {}
    eco_by_family: dict[str, str] = {}

    for eco, name, result in query.all():
        family = opening_family(name) or eco
        bucket = agg.setdefault(
            family, {"games_played": 0, "wins": 0, "losses": 0, "draws": 0}
        )
        bucket["games_played"] += 1
        if result == "win":
            bucket["wins"] += 1
        elif result == "draw":
            bucket["draws"] += 1
        else:
            bucket["losses"] += 1
        eco_by_family.setdefault(family, eco)

    stats = []
    for family, bucket in agg.items():
        games = bucket["games_played"]
        win_rate = round((bucket["wins"] / games) * 100, 1) if games else 0.0
        stats.append(
            OpeningStat(
                opening_eco=eco_by_family[family],
                opening_name=family,
                wins=bucket["wins"],
                losses=bucket["losses"],
                draws=bucket["draws"],
                games_played=games,
                win_rate=win_rate,
            )
        )

    stats.sort(key=lambda s: s.win_rate)
    return stats


def get_performance_by_time_class(db: Session, owner_id: str) -> list[TimeClassStat]:
    rows = db.query(
        Game.time_class,
        func.count(Game.id).label("games"),
        func.sum(case((Game.result == "win", 1), else_=0)).label("wins"),
        func.sum(case((Game.result == "loss", 1), else_=0)).label("losses"),
        func.sum(case((Game.result == "draw", 1), else_=0)).label("draws"),
    ).filter(
        Game.owner_id == owner_id,
        Game.time_class.isnot(None),
    ).group_by(Game.time_class).all()

    stats = []
    for row in rows:
        total = row.games or 0
        win_rate = round((row.wins / total) * 100, 1) if total else 0.0
        stats.append(
            TimeClassStat(
                time_class=row.time_class,
                games=total,
                wins=row.wins,
                losses=row.losses,
                draws=row.draws,
                win_rate=win_rate,
            )
        )

    stats.sort(key=lambda s: s.games, reverse=True)
    return stats


def get_color_split(db: Session, owner_id: str) -> dict[str, dict]:
    rows = db.query(
        Game.color,
        func.count(Game.id),
        func.sum(case((Game.result == "win", 1), else_=0)),
    ).filter(
        Game.owner_id == owner_id,
        Game.color.isnot(None),
    ).group_by(Game.color).all()

    split: dict[str, dict] = {}
    for color, games, wins in rows:
        split[color] = {
            "games": games or 0,
            "wins": wins or 0,
            "win_rate": round((wins / games) * 100, 1) if games else 0.0,
        }
    return split


def get_rating_trend(points: list[tuple]) -> dict:
    """
    Recebe [(played_at, rating)] ordenado e compara o último ponto com o
    ponto mais próximo de ~30 dias atrás.
    """
    if len(points) < 2:
        return {"delta_30d": 0, "current": points[-1][1] if points else 0}

    current_rating = points[-1][1]
    current_date = points[-1][0]

    reference = points[0]
    for played_at, rating in reversed(points):
        if (current_date - played_at).days <= 30:
            reference = (played_at, rating)
        else:
            break

    return {
        "delta_30d": current_rating - reference[1],
        "current": current_rating,
    }


def build_insights(
    db: Session,
    owner_id: str,
    username: str | None,
    color: chess.Color | None = None,
) -> list[dict]:
    """Regras simples sobre os dados reais — sem motor, mas sem inventar."""
    insights: list[dict] = []

    openings = get_opening_stats(db, owner_id)
    relevant = [o for o in openings if o.games_played >= MIN_GAMES_FOR_INSIGHT]

    if relevant:
        worst = relevant[0]
        insights.append({
            "kind": "weakness",
            "title": f"Abertura mais fraca: {worst.opening_name}",
            "message": (
                f"{worst.win_rate}% de vitórias em {worst.games_played} partidas "
                f"({worst.losses} derrotas, {worst.draws} empates). "
                "Vale focar treino aqui."
            ),
        })

        best = max(relevant, key=lambda o: o.win_rate)
        if best.opening_name != worst.opening_name:
            insights.append({
                "kind": "strength",
                "title": f"Ponto forte: {best.opening_name}",
                "message": (
                    f"{best.win_rate}% de vitórias em {best.games_played} partidas. "
                    "É aqui que o teu repertório funciona."
                ),
            })

    perf = get_performance_by_time_class(db, owner_id)
    rated_perf = [p for p in perf if p.games >= MIN_GAMES_FOR_INSIGHT]
    if len(rated_perf) >= 2:
        slowest = min(rated_perf, key=lambda p: p.win_rate)
        fastest = max(rated_perf, key=lambda p: p.win_rate)
        insights.append({
            "kind": "weakness" if slowest.win_rate < 45 else "trend",
            "title": f"Ritmo mais fraco: {slowest.time_class}",
            "message": (
                f"{slowest.win_rate}% de vitórias no {slowest.time_class} "
                f"contra {fastest.win_rate}% no {fastest.time_class}."
            ),
        })

    split = get_color_split(db, owner_id)
    white = split.get("white")
    black = split.get("black")
    if white and black and white["games"] >= MIN_GAMES_FOR_INSIGHT \
            and black["games"] >= MIN_GAMES_FOR_INSIGHT:
        gap = white["win_rate"] - black["win_rate"]
        if abs(gap) >= 8:
            better, worse = ("brancas", "pretas") if gap > 0 else ("pretas", "brancas")
            hi, lo = (white, black) if gap > 0 else (black, white)
            insights.append({
                "kind": "pattern",
                "title": f"Diferença entre cores: {abs(gap)} pontos",
                "message": (
                    f"Ganhas {hi['win_rate']}% com as {better} mas só "
                    f"{lo['win_rate']}% com as {worse}."
                ),
            })

    return insights
