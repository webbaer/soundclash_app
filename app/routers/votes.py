from fastapi import APIRouter, HTTPException
from .. import schemas
from .. import redis_store as store

router = APIRouter(prefix="/votes", tags=["votes"])


@router.post("/{game_code}/{round_id}", response_model=schemas.VoteOut)
def cast_vote(game_code: str, round_id: int, vote_in: schemas.VoteCreate):
    try:
        vote = store.add_vote(
            code=game_code,
            round_id=round_id,
            voter_id=vote_in.voter_id,
            choice_id=vote_in.choice_id
        )
    except ValueError as e:
        msg = str(e)
        if "Game not found" in msg or "Round not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return schemas.VoteOut(**vote.model_dump())


@router.post("/winner/{game_code}/{round_id}")
def decide_winner(game_code: str, round_id: int):
    try:
        winner_choice = store.compute_winner_and_finish_round(
            code=game_code,
            round_id=round_id
        )
    except ValueError as e:
        msg = str(e)
        if "Game not found" in msg or "Round not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    if not winner_choice:
        return {"message": "No votes cast"}

    return {
        "winner_song_title": winner_choice.song_title,
        "winner_artist": winner_choice.artist,
        "winner_player_id": winner_choice.player_id
    }
