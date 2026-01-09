from fastapi import APIRouter, HTTPException
from ..schemas import PlayerCreate, PlayerOut
from .. import redis_store as store

router = APIRouter(prefix="/players", tags=["players"])


@router.post("/join/{game_code}", response_model=PlayerOut)
def join_game(game_code: str, player_in: PlayerCreate):
    # check if game exists
    try:
        store._load_game_or_raise(game_code)
    except ValueError:
        raise HTTPException(status_code=404, detail="Game not found")

    try:
        player = store.add_player(
            code=game_code,
            name=player_in.name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PlayerOut(**player.model_dump())