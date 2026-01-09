from fastapi import FastAPI


from .routers import games, players, rounds, votes




app = FastAPI(title="SoundClash Backend")


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(games.router)
app.include_router(players.router)
app.include_router(rounds.router)
app.include_router(votes.router)
