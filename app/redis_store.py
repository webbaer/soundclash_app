# app/redis_store.py
import os
import random
import string
from enum import Enum
from typing import List, Optional

import redis
from pydantic import BaseModel, Field

# Redis-Client (per Env konfigurierbar, Default lokal)
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
    decode_responses=True,
)


class GameStatus(str, Enum):
    lobby = "lobby"
    song_selection = "song_selection"
    voting = "voting"
    results = "results"
    finished = "finished"


class RoundStatus(str, Enum):
    song_selection = "song_selection"
    voting = "voting"
    results = "results"
    finished = "finished"


class Player(BaseModel):
    id: int
    name: str
    score: int = 0
    is_host: bool = False


class SongChoice(BaseModel):
    id: int
    player_id: int
    song_title: str
    artist: str
    url: Optional[str] = None


class Vote(BaseModel):
    id: int
    voter_id: int
    choice_id: int


class Round(BaseModel):
    id: int
    index: int
    category: str
    status: RoundStatus = RoundStatus.song_selection
    choices: List[SongChoice] = Field(default_factory=list)
    votes: List[Vote] = Field(default_factory=list)


class Game(BaseModel):
    code: str
    status: GameStatus = GameStatus.lobby
    max_rounds: Optional[int] = None
    players: List[Player] = Field(default_factory=list)
    rounds: List[Round] = Field(default_factory=list)

    # interne Counters für IDs
    next_player_id: int = 1
    next_round_id: int = 1
    next_choice_id: int = 1
    next_vote_id: int = 1


def _game_key(code: str) -> str:
    return f"game:{code}"

def _load_game_or_raise(code: str) -> Game:
    game = load_game(code)
    if not game:
        raise ValueError("Game not found")
    return game

def save_game(game: Game) -> None:
    # Wir speichern das komplette Game als JSON-String
    r.set(_game_key(game.code), game.model_dump_json())


def load_game(code: str) -> Optional[Game]:
    data = r.get(_game_key(code))
    if not data:
        return None
    return Game.model_validate_json(data)


def generate_game_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def create_game(max_rounds: Optional[int] = None, code: Optional[str] = None) -> Game:
    if code is None:
        code = generate_game_code()
        while r.exists(_game_key(code)):
            code = generate_game_code()

    game = Game(code=code, max_rounds=max_rounds)
    save_game(game)
    return game

def add_player(code: str, name: str) -> Player:
    game = _load_game_or_raise(code)

    # Host = erster Spieler
    is_host = len(game.players) == 0

    player = Player(
        id=game.next_player_id,
        name=name,
        is_host=is_host,
    )
    game.next_player_id += 1
    game.players.append(player)
    save_game(game)
    return player

def start_new_round(code: str, category: str) -> Round:
    game = _load_game_or_raise(code)

    if game.status not in [GameStatus.lobby, GameStatus.results]:
        raise ValueError("Cannot start new round in current game status")

    existing_rounds = len(game.rounds)
    if game.max_rounds is not None and existing_rounds >= game.max_rounds:
        raise ValueError("Max rounds reached")

    round_obj = Round(
        id=game.next_round_id,
        index=existing_rounds + 1,
        category=category,
    )
    game.next_round_id += 1
    game.rounds.append(round_obj)
    game.status = GameStatus.song_selection

    save_game(game)
    return round_obj

def get_current_round(code: str) -> Optional[Round]:
    game = load_game(code)
    if not game or not game.rounds:
        return None
    return game.rounds[-1]


def add_song_choice(code: str, round_id: int, player_id: int, song_title: str, artist: str, url: Optional[str] = None) -> SongChoice:
    game = _load_game_or_raise(code)

    round_obj = next((r for r in game.rounds if r.id == round_id), None)
    if not round_obj:
        raise ValueError("Round not found")

    if round_obj.status != RoundStatus.song_selection:
        raise ValueError("Round not in song_selection state")

    choice = SongChoice(
        id=game.next_choice_id,
        player_id=player_id,
        song_title=song_title,
        artist=artist,
        url=url,
    )
    game.next_choice_id += 1
    round_obj.choices.append(choice)

    save_game(game)
    return choice

def start_voting(code: str, round_id: int) -> None:
    game = _load_game_or_raise(code)

    round_obj = next((r for r in game.rounds if r.id == round_id), None)
    if not round_obj:
        raise ValueError("Round not found")

    if round_obj.status != RoundStatus.song_selection:
        raise ValueError("Round not in song_selection state")

    round_obj.status = RoundStatus.voting
    game.status = GameStatus.voting
    save_game(game)


def add_vote(code: str, round_id: int, voter_id: int, choice_id: int) -> Vote:
    game = _load_game_or_raise(code)

    round_obj = next((r for r in game.rounds if r.id == round_id), None)
    if not round_obj:
        raise ValueError("Round not found")

    if round_obj.status != RoundStatus.voting:
        raise ValueError("Round not in voting state")

    choice = next((c for c in round_obj.choices if c.id == choice_id), None)
    if not choice:
        raise ValueError("Choice not found")

    if choice.player_id == voter_id:
        raise ValueError("Cannot vote for yourself")

    if any(v.voter_id == voter_id for v in round_obj.votes):
        raise ValueError("Already voted")

    vote = Vote(
        id=game.next_vote_id,
        voter_id=voter_id,
        choice_id=choice_id,
    )
    game.next_vote_id += 1
    round_obj.votes.append(vote)
    save_game(game)
    return vote

def compute_winner_and_finish_round(code: str, round_id: int):
    game = _load_game_or_raise(code)

    round_obj = next((r for r in game.rounds if r.id == round_id), None)
    if not round_obj:
        raise ValueError("Round not found")

    if round_obj.status != RoundStatus.voting:
        raise ValueError("Round not in voting state")

    if not round_obj.votes:
        round_obj.status = RoundStatus.results
        game.status = GameStatus.results
        save_game(game)
        return None

    # Votes zählen
    counts: dict[int, int] = {}
    for v in round_obj.votes:
        counts[v.choice_id] = counts.get(v.choice_id, 0) + 1

    winner_choice_id = max(counts, key=counts.get)
    winner_choice = next(c for c in round_obj.choices if c.id == winner_choice_id)

    # Punkte verteilen
    winner_player = next(p for p in game.players if p.id == winner_choice.player_id)
    winner_player.score += counts[winner_choice_id]

    round_obj.status = RoundStatus.results
    game.status = GameStatus.results
    save_game(game)

    return winner_choice

def finish_game(code: str) -> Game:
    game = _load_game_or_raise(code)
    game.status = GameStatus.finished
    save_game(game)
    return game

#test