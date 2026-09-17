from fastapi import APIRouter, HTTPException

from .. import schemas
from .. import redis_store as store

router = APIRouter(prefix="/games", tags=["games"])


@router.post("/", response_model=schemas.GameOut)
def create_game(game_in: schemas.GameCreate):
    # Neues Game in Redis erzeugen
    game = store.create_game(max_rounds=game_in.max_rounds)

    return schemas.GameOut(
        code=game.code,
        status=game.status,
        max_rounds=game.max_rounds,
        players=[schemas.PlayerOut(**p.model_dump()) for p in game.players],
    )


@router.get("/{code}", response_model=schemas.GameOut)
def get_game(code: str):
    game = store.load_game(code)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    return schemas.GameOut(
        code=game.code,
        status=game.status,
        max_rounds=game.max_rounds,
        players=[schemas.PlayerOut(**p.model_dump()) for p in game.players],
    )


@router.get("/{code}/state", response_model=schemas.GameStateOut)
def get_game_state(code: str):
    game = store.load_game(code)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    # aktuelle Runde = letzte Runde in der Liste (oder None, falls noch keine existiert)
    current_round = game.rounds[-1] if game.rounds else None

    game_out = schemas.GameOut(
        code=game.code,
        status=game.status,
        max_rounds=game.max_rounds,
        players=[schemas.PlayerOut(**p.model_dump()) for p in game.players],
    )

    if not current_round:
        return schemas.GameStateOut(game=game_out, current_round=None)

    round_out = schemas.RoundOut(
        id=current_round.id,
        index=current_round.index,
        category=current_round.category,
        status=current_round.status,
        choices=[schemas.SongChoiceOut(**c.model_dump()) for c in current_round.choices],
        votes=[schemas.VoteOut(**v.model_dump()) for v in current_round.votes],
        winner_choice_id=current_round.winner_choice_id,
    )

    return schemas.GameStateOut(
        game=game_out,
        current_round=round_out,
    )

@router.post("/{code}/finish")
def finish_game(code: str):
    try:
        game = store.finish_game(code)
    except ValueError:
        raise HTTPException(status_code=404, detail="Game not found")

    return {
        "message": "Game finished",
        "code": game.code,
        "status": game.status,
    }