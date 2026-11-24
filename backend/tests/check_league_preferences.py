"""Regression checks for personal league preferences and malformed lineup responses."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.routes import get_session, get_state, get_viewer, router
from auth.accounts import Viewer
from core.config import Settings
from db import _add_missing_columns, create_db_engine, init_db
from db.models import League, UserLeague
from sync.automation import parse_lineup


def main():
    assert parse_lineup({"it": [{"i": str(i)} for i in range(1, 19)]}) == (None, [])
    assert parse_lineup({"lp": ["1", "1", "0", "2"]})[1] == ["1", "2"]
    assert parse_lineup({"type": "4-4-2", "lp": list(range(1, 12))}) == (
        "4-4-2",
        [str(i) for i in range(1, 12)],
    )

    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        session.add_all(
            [
                League(id="10", name="Same name"),
                League(id="20", name="Same name"),
                UserLeague(user_id="1", league_id="10"),
                UserLeague(user_id="1", league_id="20"),
                UserLeague(user_id="2", league_id="10"),
            ]
        )
        session.commit()

    app = FastAPI()
    app.include_router(router)

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_state] = lambda: SimpleNamespace(settings=Settings(), cache={})
    app.dependency_overrides[get_viewer] = lambda: Viewer("1", "One", None, ("10", "20"), "session")
    with TestClient(app) as client:
        response = client.put("/api/leagues/preference?league=10", json={"inactive": True})
        assert response.status_code == 200, response.text
        assert [item["inactive"] for item in response.json()["leagues"]] == [True, False]
        rules = client.put(
            "/api/leagues/preference?league=10", json={"analysisSquadLimit": 20, "analysisClubLimit": 4}
        )
        assert rules.status_code == 200
        assert rules.json()["leagues"][0]["analysisClubLimit"] == 4
        assert rules.json()["leagues"][0]["inactive"] is True
        assert (
            client.put("/api/leagues/preference?league=10", json={"analysisClubLimit": 0}).status_code == 422
        )
        assert client.put("/api/leagues/preference?league=99", json={"inactive": True}).status_code == 404
        with Session(engine) as session:
            assert not session.get(UserLeague, ("2", "10")).inactive
            assert session.get(UserLeague, ("2", "10")).analysis_club_limit == 3
            assert session.get(UserLeague, ("1", "20")).analysis_squad_limit == 18
        app.dependency_overrides.pop(get_viewer)
        app.dependency_overrides[get_viewer] = lambda: Viewer("2", "Two", None, ("10",), "other")
        assert client.get("/api/auth/me").json()["leagues"][0]["inactive"] is False

    old = create_db_engine("sqlite://")
    with old.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE userleague (user_id VARCHAR, league_id VARCHAR, budget BIGINT)"
        )
        connection.exec_driver_sql("INSERT INTO userleague VALUES ('1', '10', 123456)")
    _add_missing_columns(old)
    _add_missing_columns(old)
    with old.connect() as connection:
        assert tuple(connection.exec_driver_sql("SELECT budget, inactive FROM userleague").one()) == (
            123456,
            0,
        )
    try:
        init_db(old)
    except RuntimeError as error:
        assert "No data was changed" in str(error)
    else:
        raise AssertionError("Old schemas must not be silently dropped")
    with old.connect() as connection:
        assert connection.exec_driver_sql("SELECT budget FROM userleague").scalar_one() == 123456
    print("PASS: league isolation, unauthorized league, additive migration and lineup bounds")


if __name__ == "__main__":
    main()
