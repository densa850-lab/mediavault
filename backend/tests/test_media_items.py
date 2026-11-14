"""Ownership checks on the media_items STUB, incl. two-user IDOR tests (real PostgreSQL)."""

import uuid

from fastapi.testclient import TestClient

from tests.test_auth import A, B, auth, login, register, sql


def _two_users(c: TestClient) -> tuple[dict, dict]:
    register(c, A)
    register(c, B)
    return auth(login(c, A)), auth(login(c, B))


def test_crud_own_items(db_client: TestClient) -> None:
    a, _ = _two_users(db_client)
    created = db_client.post("/api/v1/media-items", json={"title": "Holiday clip"}, headers=a)
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert db_client.get(f"/api/v1/media-items/{item_id}", headers=a).json()["title"] == (
        "Holiday clip"
    )
    upd = db_client.patch(f"/api/v1/media-items/{item_id}", json={"title": "Renamed"}, headers=a)
    assert upd.status_code == 200 and upd.json()["title"] == "Renamed"
    assert [i["id"] for i in db_client.get("/api/v1/media-items", headers=a).json()] == [item_id]
    assert db_client.delete(f"/api/v1/media-items/{item_id}", headers=a).status_code == 204
    assert db_client.get(f"/api/v1/media-items/{item_id}", headers=a).status_code == 404


def test_idor_user_a_cannot_touch_user_b_items(db_client: TestClient) -> None:
    a, b = _two_users(db_client)
    b_item = db_client.post("/api/v1/media-items", json={"title": "B private"}, headers=b).json()
    url = f"/api/v1/media-items/{b_item['id']}"

    # Read, update and delete as A: all 404, identical to a non-existent id.
    missing = db_client.get(f"/api/v1/media-items/{uuid.uuid4()}", headers=a)
    read = db_client.get(url, headers=a)
    assert read.status_code == missing.status_code == 404
    assert read.json() == missing.json() == {"detail": "Not found."}
    assert db_client.patch(url, json={"title": "pwned"}, headers=a).status_code == 404
    assert db_client.delete(url, headers=a).status_code == 404

    # A's list never includes B's rows.
    assert db_client.get("/api/v1/media-items", headers=a).json() == []

    # B's item is untouched.
    still = db_client.get(url, headers=b)
    assert still.status_code == 200 and still.json()["title"] == "B private"
    assert sql("SELECT count(*) FROM media_items")[0][0] == 1


def test_owner_cannot_be_spoofed_on_create(db_client: TestClient) -> None:
    a, b = _two_users(db_client)
    (b_id,) = sql("SELECT id FROM users WHERE email = :e", e=B)[0]
    res = db_client.post(
        "/api/v1/media-items",
        json={"title": "sneaky", "owner_id": str(b_id)},  # extra field is ignored
        headers=a,
    )
    assert res.status_code == 201
    assert db_client.get("/api/v1/media-items", headers=b).json() == []
    (owner,) = sql("SELECT u.email FROM media_items m JOIN users u ON u.id = m.owner_id")[0]
    assert owner == A


def test_media_items_require_authentication(db_client: TestClient) -> None:
    assert db_client.get("/api/v1/media-items").status_code == 401
    assert db_client.post("/api/v1/media-items", json={"title": "x"}).status_code == 401
    rid = uuid.uuid4()
    assert db_client.get(f"/api/v1/media-items/{rid}").status_code == 401
    assert db_client.delete(f"/api/v1/media-items/{rid}").status_code == 401


def test_revoked_session_loses_access_to_items(db_client: TestClient) -> None:
    register(db_client, A)
    tokens = login(db_client, A)
    a = auth(tokens)
    db_client.post("/api/v1/media-items", json={"title": "mine"}, headers=a)
    db_client.post("/api/v1/auth/logout", headers=a)
    assert db_client.get("/api/v1/media-items", headers=a).status_code == 401


def test_title_validation(db_client: TestClient) -> None:
    a, _ = _two_users(db_client)
    assert db_client.post("/api/v1/media-items", json={"title": ""}, headers=a).status_code == 422
    long = db_client.post("/api/v1/media-items", json={"title": "x" * 201}, headers=a)
    assert long.status_code == 422
