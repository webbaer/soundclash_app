# app/redis_store.py
import os
import random
import string
from enum import Enum
from typing import Callable, List, Optional, Tuple, TypeVar

import redis
from pydantic import BaseModel, Field

# Redis-Client (per Env konfigurierbar, Default lokal)
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
    decode_responses=True,
)

# Wie oft eine Mutation bei einem Schreibkonflikt wiederholt wird
MAX_WRITE_RETRIES = 25

# Wie oft ein freier Game-Code gesucht wird
MAX_CODE_ATTEMPTS = 25


class ConcurrencyError(RuntimeError):
    """Mutation konnte trotz mehrerer Versuche nicht gespeichert werden."""


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
    winner_choice_id: Optional[int] = None


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


T = TypeVar("T")


def _game_key(code: str) -> str:
    return f"game:{code}"


def save_game(game: Game) -> None:
    # Wir speichern das komplette Game als JSON-String
    r.set(_game_key(game.code), game.model_dump_json())


def load_game(code: str) -> Optional[Game]:
    data = r.get(_game_key(code))
    if not data:
        return None
    return Game.model_validate_json(data)


def _load_game_or_raise(code: str) -> Game:
    game = load_game(code)
    if not game:
        raise ValueError("Game not found")
    return game


def _mutate_game(code: str, mutator: Callable[[Game], T]) -> Tuple[Game, T]:
    """Liest ein Game, wendet `mutator` darauf an und schreibt es zurueck.

    Laeuft als Redis-Transaktion: WATCH auf den Key, Aenderung in MULTI/EXEC.
    Hat jemand anders zwischen Lesen und Schreiben denselben Key geaendert,
    schlaegt EXEC fehl und der Mutator laeuft auf dem frischen Stand erneut.
    Ohne das wuerden parallele Writes (z.B. zwei gleichzeitige Votes)
    einander ueberschreiben.

    Der Mutator kann mehrfach aufgerufen werden und darf deshalb nur das
    uebergebene Game veraendern, nichts ausserhalb.
    """
    key = _game_key(code)

    for _ in range(MAX_WRITE_RETRIES):
        with r.pipeline() as pipe:
            pipe.watch(key)

            data = pipe.get(key)
            if not data:
                pipe.unwatch()
                raise ValueError("Game not found")

            game = Game.model_validate_json(data)

            # Validierungsfehler fliegen hier raus, bevor irgendwas geschrieben wird
            result = mutator(game)

            pipe.multi()
            pipe.set(key, game.model_dump_json())
            try:
                pipe.execute()
            except redis.exceptions.WatchError:
                continue  # jemand war schneller -> nochmal von vorn

            return game, result

    raise ConcurrencyError("Game was modified concurrently, please retry")


def _find_round(game: Game, round_id: int) -> Round:
    round_obj = next((rnd for rnd in game.rounds if rnd.id == round_id), None)
    if not round_obj:
        raise ValueError("Round not found")
    return round_obj


def generate_game_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def create_game(max_rounds: Optional[int] = None, code: Optional[str] = None) -> Game:
    if code is not None:
        game = Game(code=code, max_rounds=max_rounds)
        save_game(game)
        return game

    # SET NX: belegt den Code nur, wenn er noch frei ist. Ein getrenntes
    # exists() davor waere ein Rennen zwischen zwei parallelen Spielen.
    for _ in range(MAX_CODE_ATTEMPTS):
        game = Game(code=generate_game_code(), max_rounds=max_rounds)
        if r.set(_game_key(game.code), game.model_dump_json(), nx=True):
            return game

    raise ConcurrencyError("Could not find a free game code")


def add_player(code: str, name: str) -> Player:
    def mutate(game: Game) -> Player:
        # Host = erster Spieler
        player = Player(
            id=game.next_player_id,
            name=name,
            is_host=len(game.players) == 0,
        )
        game.next_player_id += 1
        game.players.append(player)
        return player

    _, player = _mutate_game(code, mutate)
    return player


def start_new_round(code: str, category: str) -> Round:
    def mutate(game: Game) -> Round:
        # max_rounds zuerst pruefen: nach der letzten Runde steht das Game auf
        # finished, und "Max rounds reached" sagt mehr als der Status-Fehler.
        if game.max_rounds is not None and len(game.rounds) >= game.max_rounds:
            raise ValueError("Max rounds reached")

        if game.status not in [GameStatus.lobby, GameStatus.results]:
            raise ValueError("Cannot start new round in current game status")

        round_obj = Round(
            id=game.next_round_id,
            index=len(game.rounds) + 1,
            category=category,
        )
        game.next_round_id += 1
        game.rounds.append(round_obj)
        game.status = GameStatus.song_selection
        return round_obj

    _, round_obj = _mutate_game(code, mutate)
    return round_obj


def get_current_round(code: str) -> Optional[Round]:
    game = load_game(code)
    if not game or not game.rounds:
        return None
    return game.rounds[-1]


def add_song_choice(
    code: str,
    round_id: int,
    player_id: int,
    song_title: str,
    artist: str,
    url: Optional[str] = None,
) -> SongChoice:
    def mutate(game: Game) -> SongChoice:
        round_obj = _find_round(game, round_id)

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
        return choice

    _, choice = _mutate_game(code, mutate)
    return choice


def start_voting(code: str, round_id: int) -> None:
    def mutate(game: Game) -> None:
        round_obj = _find_round(game, round_id)

        if round_obj.status != RoundStatus.song_selection:
            raise ValueError("Round not in song_selection state")

        round_obj.status = RoundStatus.voting
        game.status = GameStatus.voting

    _mutate_game(code, mutate)


def eligible_voter_ids(game: Game, round_obj: Round) -> set:
    """Spieler, die in dieser Runde ueberhaupt abstimmen koennen.

    Fuer den eigenen Song darf niemand stimmen. Wer als Einziger einen Song
    eingereicht hat, hat also nichts zu waehlen und zaehlt nicht mit --
    sonst wuerde die Runde nie vollstaendig werden.
    """
    return {
        p.id
        for p in game.players
        if any(c.player_id != p.id for c in round_obj.choices)
    }


def all_votes_cast(game: Game, round_obj: Round) -> bool:
    eligible = eligible_voter_ids(game, round_obj)
    if not eligible:
        return False
    return eligible <= {v.voter_id for v in round_obj.votes}


def _finalize_round(game: Game, round_obj: Round) -> Optional[SongChoice]:
    """Zaehlt die Votes aus, vergibt Punkte und schliesst die Runde ab."""
    counts: dict[int, int] = {}
    for v in round_obj.votes:
        counts[v.choice_id] = counts.get(v.choice_id, 0) + 1

    winner_choice: Optional[SongChoice] = None
    if counts:
        winner_choice_id = max(counts, key=counts.get)
        winner_choice = next(c for c in round_obj.choices if c.id == winner_choice_id)
        round_obj.winner_choice_id = winner_choice_id

        # Ein Punkt pro erhaltenem Vote
        winner_player = next(
            (p for p in game.players if p.id == winner_choice.player_id), None
        )
        if winner_player:
            winner_player.score += counts[winner_choice_id]

    round_obj.status = RoundStatus.results

    # War das die letzte erlaubte Runde, ist das Spiel vorbei
    if game.max_rounds is not None and len(game.rounds) >= game.max_rounds:
        game.status = GameStatus.finished
    else:
        game.status = GameStatus.results

    return winner_choice


def add_vote(code: str, round_id: int, voter_id: int, choice_id: int) -> Vote:
    def mutate(game: Game) -> Vote:
        round_obj = _find_round(game, round_id)

        if round_obj.status != RoundStatus.voting:
            raise ValueError("Round not in voting state")

        choice = next((c for c in round_obj.choices if c.id == choice_id), None)
        if not choice:
            raise ValueError("Choice not found")

        if choice.player_id == voter_id:
            raise ValueError("Cannot vote for yourself")

        if any(v.voter_id == voter_id for v in round_obj.votes):
            raise ValueError("Already voted")

        vote = Vote(id=game.next_vote_id, voter_id=voter_id, choice_id=choice_id)
        game.next_vote_id += 1
        round_obj.votes.append(vote)

        # Haben alle abgestimmt, muss niemand die Runde von Hand beenden
        if all_votes_cast(game, round_obj):
            _finalize_round(game, round_obj)

        return vote

    _, vote = _mutate_game(code, mutate)
    return vote


def compute_winner_and_finish_round(code: str, round_id: int) -> Optional[SongChoice]:
    def mutate(game: Game) -> Optional[SongChoice]:
        round_obj = _find_round(game, round_id)

        # Runde kann bereits automatisch beendet worden sein -> Ergebnis liefern
        if round_obj.status == RoundStatus.results:
            if round_obj.winner_choice_id is None:
                return None
            return next(
                c for c in round_obj.choices if c.id == round_obj.winner_choice_id
            )

        if round_obj.status != RoundStatus.voting:
            raise ValueError("Round not in voting state")

        return _finalize_round(game, round_obj)

    _, winner_choice = _mutate_game(code, mutate)
    return winner_choice


def finish_game(code: str) -> Game:
    def mutate(game: Game) -> None:
        game.status = GameStatus.finished

    game, _ = _mutate_game(code, mutate)
    return game
