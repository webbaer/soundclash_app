"""End-to-end Tests fuer den kompletten Spielablauf."""


def join(client, code, name):
    resp = client.post(f"/players/join/{code}", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def add_choice(client, code, round_id, player_id, title, artist):
    resp = client.post(
        f"/rounds/{code}/choice/{round_id}",
        json={"player_id": player_id, "song_title": title, "artist": artist},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_game(client):
    created = client.post("/games/", json={"max_rounds": 3}).json()
    assert len(created["code"]) == 6
    assert created["status"] == "lobby"
    assert created["players"] == []

    fetched = client.get(f"/games/{created['code']}").json()
    assert fetched == created


def test_get_unknown_game_returns_404(client):
    assert client.get("/games/NOPE00").status_code == 404


def test_join_assigns_unique_ids_and_marks_first_player_as_host(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")
    carol = join(client, game_code, "Carol")

    assert alice["is_host"] is True
    assert bob["is_host"] is False
    assert carol["is_host"] is False

    # IDs muessen fortlaufend und eindeutig sein
    assert [alice["id"], bob["id"], carol["id"]] == [1, 2, 3]

    players = client.get(f"/games/{game_code}").json()["players"]
    assert [p["name"] for p in players] == ["Alice", "Bob", "Carol"]


def test_join_unknown_game_returns_404(client):
    assert client.post("/players/join/NOPE00", json={"name": "Alice"}).status_code == 404


def test_full_round_flow_awards_points_to_winner(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")
    carol = join(client, game_code, "Carol")

    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Best 90s Song"}).json()
    assert round_obj["index"] == 1
    assert round_obj["status"] == "song_selection"

    alice_choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Smells Like Teen Spirit", "Nirvana")
    add_choice(client, game_code, round_obj["id"], bob["id"], "Wonderwall", "Oasis")

    assert client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting").status_code == 200

    # Vote-Endpoint muss das angelegte Vote zurueckgeben
    vote = client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": bob["id"], "choice_id": alice_choice["id"]},
    )
    assert vote.status_code == 200, vote.text
    assert vote.json()["voter_id"] == bob["id"]
    assert vote.json()["choice_id"] == alice_choice["id"]

    client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": carol["id"], "choice_id": alice_choice["id"]},
    )

    winner = client.post(f"/votes/winner/{game_code}/{round_obj['id']}")
    assert winner.status_code == 200, winner.text
    assert winner.json() == {
        "winner_song_title": "Smells Like Teen Spirit",
        "winner_artist": "Nirvana",
        "winner_player_id": alice["id"],
    }

    # Ein Punkt pro Vote
    players = {p["name"]: p for p in client.get(f"/games/{game_code}").json()["players"]}
    assert players["Alice"]["score"] == 2
    assert players["Bob"]["score"] == 0


def test_winner_without_votes(client, game_code):
    alice = join(client, game_code, "Alice")
    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Chill"}).json()
    add_choice(client, game_code, round_obj["id"], alice["id"], "Teardrop", "Massive Attack")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    resp = client.post(f"/votes/winner/{game_code}/{round_obj['id']}")
    assert resp.json() == {"message": "No votes cast"}


def test_cannot_vote_for_own_song(client, game_code):
    alice = join(client, game_code, "Alice")
    join(client, game_code, "Bob")
    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    resp = client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": alice["id"], "choice_id": choice["id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot vote for yourself"


def test_cannot_vote_twice(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")
    # Carol ist mit dabei, damit die Runde nach Bobs Vote noch nicht
    # vollstaendig ist und sich nicht automatisch schliesst
    join(client, game_code, "Carol")
    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    payload = {"voter_id": bob["id"], "choice_id": choice["id"]}
    assert client.post(f"/votes/{game_code}/{round_obj['id']}", json=payload).status_code == 200
    second = client.post(f"/votes/{game_code}/{round_obj['id']}", json=payload)
    assert second.status_code == 400
    assert second.json()["detail"] == "Already voted"


def test_voting_before_start_is_rejected(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")
    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")

    resp = client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": bob["id"], "choice_id": choice["id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Round not in voting state"


def test_choice_after_voting_started_is_rejected(client, game_code):
    alice = join(client, game_code, "Alice")
    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    resp = client.post(
        f"/rounds/{game_code}/choice/{round_obj['id']}",
        json={"player_id": alice["id"], "song_title": "Zu spaet", "artist": "Artist"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Round not in song_selection state"


def test_unknown_round_returns_404(client, game_code):
    join(client, game_code, "Alice")
    client.post(f"/rounds/{game_code}", json={"category": "Rock"})

    resp = client.post(
        f"/rounds/{game_code}/choice/999",
        json={"player_id": 1, "song_title": "Song", "artist": "Artist"},
    )
    assert resp.status_code == 404


def test_max_rounds_is_enforced(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")

    for expected_index in (1, 2):
        round_obj = client.post(f"/rounds/{game_code}", json={"category": f"Runde {expected_index}"})
        assert round_obj.status_code == 200, round_obj.text
        round_obj = round_obj.json()
        assert round_obj["index"] == expected_index

        choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")
        client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")
        client.post(
            f"/votes/{game_code}/{round_obj['id']}",
            json={"voter_id": bob["id"], "choice_id": choice["id"]},
        )
        client.post(f"/votes/winner/{game_code}/{round_obj['id']}")

    # max_rounds = 2 -> dritte Runde muss abgelehnt werden
    resp = client.post(f"/rounds/{game_code}", json={"category": "Eine zu viel"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Max rounds reached"


def test_game_state_reflects_current_round(client, game_code):
    alice = join(client, game_code, "Alice")

    state = client.get(f"/games/{game_code}/state").json()
    assert state["current_round"] is None
    assert state["game"]["status"] == "lobby"

    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Sommer"}).json()
    add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "Artist")

    state = client.get(f"/games/{game_code}/state").json()
    assert state["game"]["status"] == "song_selection"
    assert state["current_round"]["category"] == "Sommer"
    assert len(state["current_round"]["choices"]) == 1
    assert state["current_round"]["votes"] == []


def test_finish_game(client, game_code):
    resp = client.post(f"/games/{game_code}/finish")
    assert resp.status_code == 200
    assert resp.json()["status"] == "finished"
    assert client.get(f"/games/{game_code}").json()["status"] == "finished"


def test_finish_unknown_game_returns_404(client):
    assert client.post("/games/NOPE00/finish").status_code == 404


def test_round_closes_automatically_when_all_eligible_players_voted(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")

    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    alice_choice = add_choice(client, game_code, round_obj["id"], alice["id"], "A-Song", "A")
    bob_choice = add_choice(client, game_code, round_obj["id"], bob["id"], "B-Song", "B")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    # Nach dem ersten Vote fehlt noch einer -> Runde laeuft weiter
    client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": alice["id"], "choice_id": bob_choice["id"]},
    )
    state = client.get(f"/games/{game_code}/state").json()
    assert state["current_round"]["status"] == "voting"

    # Mit dem zweiten Vote sind alle durch -> Runde schliesst von selbst
    client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": bob["id"], "choice_id": alice_choice["id"]},
    )
    state = client.get(f"/games/{game_code}/state").json()
    assert state["current_round"]["status"] == "results"
    assert state["current_round"]["winner_choice_id"] in (
        alice_choice["id"],
        bob_choice["id"],
    )


def test_player_without_foreign_song_does_not_block_the_round(client, game_code):
    """Wer als Einziger einen Song hat, kann nicht abstimmen und zaehlt nicht mit."""
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")
    carol = join(client, game_code, "Carol")

    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Solo"}).json()
    alice_choice = add_choice(client, game_code, round_obj["id"], alice["id"], "A-Song", "A")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")

    for voter in (bob, carol):
        client.post(
            f"/votes/{game_code}/{round_obj['id']}",
            json={"voter_id": voter["id"], "choice_id": alice_choice["id"]},
        )

    # Alice fehlt in der Vote-Liste, trotzdem ist die Runde vollstaendig
    state = client.get(f"/games/{game_code}/state").json()
    assert state["current_round"]["status"] == "results"
    assert state["current_round"]["winner_choice_id"] == alice_choice["id"]
    players = {p["name"]: p for p in state["game"]["players"]}
    assert players["Alice"]["score"] == 2


def test_winner_endpoint_still_answers_after_automatic_close(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")

    round_obj = client.post(f"/rounds/{game_code}", json={"category": "Rock"}).json()
    alice_choice = add_choice(client, game_code, round_obj["id"], alice["id"], "A-Song", "A")
    client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")
    client.post(
        f"/votes/{game_code}/{round_obj['id']}",
        json={"voter_id": bob["id"], "choice_id": alice_choice["id"]},
    )

    # Runde ist bereits zu -- der Endpoint liefert trotzdem das Ergebnis,
    # und zwar mehrfach ohne die Punkte erneut zu vergeben
    for _ in range(2):
        resp = client.post(f"/votes/winner/{game_code}/{round_obj['id']}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["winner_player_id"] == alice["id"]

    players = {p["name"]: p for p in client.get(f"/games/{game_code}").json()["players"]}
    assert players["Alice"]["score"] == 1


def test_game_finishes_after_the_last_round(client, game_code):
    alice = join(client, game_code, "Alice")
    bob = join(client, game_code, "Bob")

    # game_code-Fixture setzt max_rounds = 2
    for round_number in (1, 2):
        round_obj = client.post(
            f"/rounds/{game_code}", json={"category": f"Runde {round_number}"}
        ).json()
        choice = add_choice(client, game_code, round_obj["id"], alice["id"], "Song", "A")
        client.post(f"/rounds/{game_code}/{round_obj['id']}/start-voting")
        client.post(
            f"/votes/{game_code}/{round_obj['id']}",
            json={"voter_id": bob["id"], "choice_id": choice["id"]},
        )

        status = client.get(f"/games/{game_code}").json()["status"]
        assert status == ("results" if round_number == 1 else "finished")
