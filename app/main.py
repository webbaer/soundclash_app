from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .redis_store import ConcurrencyError
from .routers import games, players, rounds, votes


app = FastAPI(title="SoundClash Backend")


@app.exception_handler(ConcurrencyError)
def concurrency_error_handler(request: Request, exc: ConcurrencyError):
    """Zu viele gleichzeitige Schreibzugriffe -- Client darf es erneut versuchen."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(games.router)
app.include_router(players.router)
app.include_router(rounds.router)
app.include_router(votes.router)
