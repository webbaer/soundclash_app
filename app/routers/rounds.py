from fastapi import APIRouter, HTTPException
from .. import schemas
from .. import redis_store as store

router = APIRouter(prefix="/rounds", tags=["rounds"])


@router.post("/{game_code}", response_model=schemas.RoundOut)
def create_round(game_code: str, round_in: schemas.RoundCreate):
    try:
        round_obj = store.start_new_round(game_code, round_in.category)
    except ValueError as e:
        msg = str(e)
        if "Game not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return schemas.RoundOut(
        id=round_obj.id,
        index=round_obj.index,
        category=round_obj.category,
        status=round_obj.status,
        choices=[schemas.SongChoiceOut(**c.model_dump()) for c in round_obj.choices],
        votes=[schemas.VoteOut(**v.model_dump()) for v in round_obj.votes],
    )


@router.post("/{game_code}/choice/{round_id}", response_model=schemas.SongChoiceOut)
def add_song(game_code: str, round_id: int, choice_in: schemas.SongChoiceCreate):
    try:
        choice = store.add_song_choice(
            code=game_code,
            round_id=round_id,
            player_id=choice_in.player_id,
            song_title=choice_in.song_title,
            artist=choice_in.artist,
            url=choice_in.url,
        )
    except ValueError as e:
        msg = str(e)
        if "Game not found" in msg or "Round not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return schemas.SongChoiceOut(**choice.model_dump())

@router.post("/{game_code}/{round_id}/start-voting")
def start_voting(game_code: str, round_id: int):
    try:
        store.start_voting(
            code=game_code,
            round_id=round_id,
        )
    except ValueError as e:
        msg = str(e)
        if "Game not found" in msg or "Round not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return {"message": "Voting started"}