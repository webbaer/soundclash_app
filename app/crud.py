from sqlalchemy.orm import Session
from . import models, schemas
import random
import string


def generate_game_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def create_game(db: Session, game_in: schemas.GameCreate) -> models.Game:
    code = game_in.code or generate_game_code()

    # zur Sicherheit: wenn Code schon existiert, neuen generieren
    while db.query(models.Game).filter(models.Game.code == code).first():
        code = generate_game_code()

    game = models.Game(code=code, max_rounds=game_in.max_rounds)
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


def get_game_by_code(db: Session, code: str) -> models.Game | None:
    return db.query(models.Game).filter(models.Game.code == code).first()


def create_player(db: Session, game: models.Game, player_in: schemas.PlayerCreate) -> models.Player:
    player = models.Player(
        name=player_in.name,
        is_host=1 if player_in.is_host else 0,
        game=game,
    )
    db.add(player)
    db.commit()
    db.refresh(player)
    return player


def get_players_for_game(db: Session, game_id: int) -> list[models.Player]:
    return db.query(models.Player).filter(models.Player.game_id == game_id).all()

def create_round(db: Session, game, round_in: schemas.RoundCreate):
    round_obj = models.Round(
        index=round_in.index,
        category=round_in.category,
        game=game,
    )
    db.add(round_obj)
    db.commit()
    db.refresh(round_obj)
    return round_obj


def add_song_choice(db: Session, round_obj, choice_in: schemas.SongChoiceCreate):
    choice = models.SongChoice(
        player_id=choice_in.player_id,
        round=round_obj,
        song_title=choice_in.song_title,
        artist=choice_in.artist,
        url=choice_in.url
    )
    db.add(choice)
    db.commit()
    db.refresh(choice)
    return choice


def get_round(db: Session, round_id: int):
    return db.query(models.Round).filter(models.Round.id == round_id).first()

def add_vote(db: Session, round_obj, vote_in: schemas.VoteCreate):
    # Check: Player darf nicht für seinen eigenen Song voten
    choice = db.query(models.SongChoice).filter(models.SongChoice.id == vote_in.choice_id).first()
    if not choice:
        return None, "Choice not found"

    if choice.player_id == vote_in.voter_id:
        return None, "Cannot vote for yourself"

    # Check: Player hat schon gevotet
    existing_vote = (
        db.query(models.Vote)
        .filter(models.Vote.round_id == round_obj.id, models.Vote.voter_id == vote_in.voter_id)
        .first()
    )
    if existing_vote:
        return None, "Already voted"

    vote = models.Vote(
        round=round_obj,
        voter_id=vote_in.voter_id,
        choice_id=vote_in.choice_id
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    return vote, None


def compute_round_winner(db: Session, round_obj):
    votes = round_obj.votes
    if not votes:
        return None  # niemand hat gevotet lol

    # Count votes per choice
    vote_counts = {}
    for v in votes:
        vote_counts[v.choice_id] = vote_counts.get(v.choice_id, 0) + 1

    # Winner choice_id
    winner_choice_id = max(vote_counts, key=vote_counts.get)

    winner_choice = (
        db.query(models.SongChoice)
        .filter(models.SongChoice.id == winner_choice_id)
        .first()
    )

    # Punkte vergeben (1 Punkt pro Vote)
    winner_player = winner_choice.player
    
    # Sicherheitsprüfung: Existiert der Spieler noch?
    if winner_player:
        # Falls score noch None ist (NULL in DB), nimm 0 als Basis
        current_score = winner_player.score or 0
        winner_player.score = current_score + vote_counts[winner_choice_id]

    db.commit()

    return winner_choice


def get_rounds_for_game(db: Session, game_id: int):
    return (
        db.query(models.Round)
        .filter(models.Round.game_id == game_id)
        .order_by(models.Round.index)
        .all()
    )


def start_new_round_for_game(db: Session, game: models.Game, category: str) -> models.Round:
    existing_rounds = get_rounds_for_game(db, game.id)

    # ⬅️ NEU: Check, ob max_rounds erreicht ist
    if game.max_rounds is not None and len(existing_rounds) >= game.max_rounds:
        raise ValueError("Max rounds reached")

    next_index = len(existing_rounds) + 1

    round_obj = models.Round(
        index=next_index,
        category=category,
        game=game,
    )
    db.add(round_obj)

    game.status = models.GameStatus.song_selection

    db.commit()
    db.refresh(round_obj)
    db.refresh(game)
    return round_obj

def get_current_round_for_game(db: Session, game_id: int):
    """Gibt die letzte Runde des Spiels zurück (höchster index) oder None."""
    return (
        db.query(models.Round)
        .filter(models.Round.game_id == game_id)
        .order_by(models.Round.index.desc())
        .first()
    )