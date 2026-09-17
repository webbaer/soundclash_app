"""Paralleles Schreiben darf keine Daten verlieren."""
import threading
from concurrent.futures import ThreadPoolExecutor

from app import redis_store as store

PLAYERS = 12


def _prepare_round():
    """Spiel mit PLAYERS Spielern, jeder hat einen Song eingereicht."""
    game = store.create_game(code="RACE01")
    for i in range(PLAYERS):
        store.add_player(game.code, f"Player {i}")

    round_obj = store.start_new_round(game.code, "Parallel")
    for player in store.load_game(game.code).players:
        store.add_song_choice(
            game.code, round_obj.id, player.id, f"Song {player.id}", "Artist"
        )
    store.start_voting(game.code, round_obj.id)

    game = store.load_game(game.code)
    return game, store.get_current_round(game.code)


def test_parallel_votes_are_all_persisted():
    game, round_obj = _prepare_round()
    choices = {c.player_id: c for c in round_obj.choices}
    players = game.players

    # Jeder stimmt fuer den Song des naechsten Spielers -> keine Selbstvotes
    barrier = threading.Barrier(PLAYERS)

    def vote(i):
        voter = players[i]
        target = players[(i + 1) % PLAYERS]
        barrier.wait()  # alle gleichzeitig losschicken, maximale Kollision
        return store.add_vote(
            game.code, round_obj.id, voter.id, choices[target.id].id
        )

    with ThreadPoolExecutor(max_workers=PLAYERS) as pool:
        votes = list(pool.map(vote, range(PLAYERS)))

    stored = store.get_current_round(game.code)

    # Kein Vote darf durch einen ueberschreibenden Write verloren gehen
    assert len(stored.votes) == PLAYERS
    assert {v.voter_id for v in stored.votes} == {p.id for p in players}

    # IDs muessen eindeutig vergeben worden sein
    assert len({v.id for v in stored.votes}) == PLAYERS
    assert len({v.id for v in votes}) == PLAYERS


def test_parallel_joins_are_all_persisted():
    game = store.create_game(code="RACE02")

    barrier = threading.Barrier(PLAYERS)

    def join(i):
        barrier.wait()
        return store.add_player(game.code, f"Player {i}")

    with ThreadPoolExecutor(max_workers=PLAYERS) as pool:
        players = list(pool.map(join, range(PLAYERS)))

    stored = store.load_game(game.code)

    assert len(stored.players) == PLAYERS
    assert len({p.id for p in stored.players}) == PLAYERS
    assert len({p.id for p in players}) == PLAYERS

    # Genau ein Host, egal in welcher Reihenfolge die Threads durchkamen
    assert sum(1 for p in stored.players if p.is_host) == 1


def test_write_conflict_does_not_overwrite_other_changes():
    """Deterministischer Nachweis des Lost-Update-Problems.

    Ein Schreiber wird mitten in der Mutation angehalten, ein zweiter
    laeuft in dieser Zeit komplett durch. Ohne Transaktion wuerde der
    erste beim Speichern die Aenderung des zweiten ueberschreiben.
    """
    store.create_game(code="RACE03")
    store.add_player("RACE03", "Alice")

    entered = threading.Event()
    may_continue = threading.Event()

    def slow_mutator(game):
        # Nur der erste Durchlauf haelt an; nach einem Retry laeuft er durch.
        if not entered.is_set():
            entered.set()
            assert may_continue.wait(timeout=5)
        game.players.append(
            store.Player(id=game.next_player_id, name="Slow", is_host=False)
        )
        game.next_player_id += 1

    slow = threading.Thread(target=store._mutate_game, args=("RACE03", slow_mutator))
    slow.start()

    assert entered.wait(timeout=5), "Mutator ist nie angelaufen"
    store.add_player("RACE03", "Bob")  # kommt waehrenddessen komplett durch
    may_continue.set()
    slow.join(timeout=5)
    assert not slow.is_alive()

    players = store.load_game("RACE03").players
    assert {p.name for p in players} == {"Alice", "Bob", "Slow"}
    assert len({p.id for p in players}) == 3


def test_exhausted_retries_answer_with_503(client, monkeypatch):
    """Gibt ein Schreibkonflikt nicht nach, kommt 503 statt eines 500ers."""
    code = client.post("/games/", json={}).json()["code"]
    monkeypatch.setattr(store, "MAX_WRITE_RETRIES", 0)

    resp = client.post(f"/players/join/{code}", json={"name": "Alice"})
    assert resp.status_code == 503
    assert "concurrently" in resp.json()["detail"]
