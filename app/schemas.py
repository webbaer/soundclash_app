from typing import List, Optional
from pydantic import BaseModel

from .redis_store import GameStatus, RoundStatus


# ---------------------------
# Player Schemas
# ---------------------------

class PlayerCreate(BaseModel):
    name: str


class PlayerOut(BaseModel):
    id: int
    name: str
    score: int
    is_host: bool


# ---------------------------
# Song Choice Schemas
# ---------------------------

class SongChoiceCreate(BaseModel):
    player_id: int
    song_title: str
    artist: str
    url: Optional[str] = None


class SongChoiceOut(BaseModel):
    id: int
    player_id: int
    song_title: str
    artist: str
    url: Optional[str]


# ---------------------------
# Vote Schemas
# ---------------------------

class VoteCreate(BaseModel):
    voter_id: int
    choice_id: int


class VoteOut(BaseModel):
    id: int
    voter_id: int
    choice_id: int


# ---------------------------
# Round Schemas
# ---------------------------

class RoundCreate(BaseModel):
    category: str


class RoundOut(BaseModel):
    id: int
    index: int
    category: str
    status: RoundStatus
    choices: List[SongChoiceOut]
    votes: List[VoteOut]
    winner_choice_id: Optional[int] = None


# ---------------------------
# Game Schemas
# ---------------------------

class GameCreate(BaseModel):
    max_rounds: Optional[int] = None


class GameOut(BaseModel):
    code: str
    status: GameStatus
    max_rounds: Optional[int]
    players: List[PlayerOut]


# ---------------------------
# GameState Schema (Frontend wichtig!)
# ---------------------------

class GameStateOut(BaseModel):
    game: GameOut
    current_round: Optional[RoundOut]