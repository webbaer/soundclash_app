from sqlalchemy import Column, Integer, String, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from .db import Base


class GameStatus(str, enum.Enum):
    lobby = "lobby"
    song_selection = "song_selection"
    voting = "voting"
    results = "results"
    finished = "finished"


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    status = Column(Enum(GameStatus), default=GameStatus.lobby)

    max_rounds = Column(Integer, nullable=True)

    players = relationship("Player", back_populates="game", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    score = Column(Integer, default=0)
    is_host = Column(Integer, default=0)  # 0/1 als bool

    game_id = Column(Integer, ForeignKey("games.id"))
    game = relationship("Game", back_populates="players")

class RoundStatus(str, enum.Enum):
    song_selection = "song_selection"
    voting = "voting"
    results = "results"
    finished = "finished"


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, index=True)
    index = Column(Integer)  # Runde 1, 2, 3...
    category = Column(String)
    status = Column(Enum(RoundStatus), default=RoundStatus.song_selection)

    game_id = Column(Integer, ForeignKey("games.id"))
    game = relationship("Game", backref="rounds")

    choices = relationship("SongChoice", back_populates="round", cascade="all, delete-orphan")


class SongChoice(Base):
    __tablename__ = "song_choices"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    round_id = Column(Integer, ForeignKey("rounds.id"))

    song_title = Column(String)
    artist = Column(String)
    url = Column(String, nullable=True)

    round = relationship("Round", back_populates="choices")
    player = relationship("Player")

class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, index=True)

    round_id = Column(Integer, ForeignKey("rounds.id"))
    round = relationship("Round", backref="votes")

    voter_id = Column(Integer, ForeignKey("players.id"))
    voter = relationship("Player")

    choice_id = Column(Integer, ForeignKey("song_choices.id"))
    choice = relationship("SongChoice")
