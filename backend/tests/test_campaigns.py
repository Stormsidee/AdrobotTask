from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import DailyStat


@pytest.fixture
def api(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.sqlite3'}"
    monkeypatch.setenv("ADROBOT_DATABASE_URL", url)
    monkeypatch.setenv("ADROBOT_MODE", "demo")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings(database_url=url, mode="demo"))) as client:
        yield client, url


def campaign(client, **changes):
    return client.post("/api/campaigns", json={
        "name": "campaign1", "country": "de", "domain_id": 1, "source_id": 1,
        "group_id": 1, "offer_id": 101, **changes,
    })


def test_create_and_validate_campaign(api):
    client, _ = api
    response = campaign(client)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test_kalinin_campaign1"
    streams = client.get(f"/api/campaigns/{data['id']}/streams").json()
    assert len(streams) == 2
    assert streams[0]["editable"] is False
    assert streams[1]["id"] == data["stream_id"]
    assert streams[1]["offers"][0]["offer_id"] == 101
    assert campaign(client).status_code == 409
    assert campaign(client, domain_id=999).status_code == 422
    assert campaign(client, country="DEU").status_code == 422


def test_editor_guards_and_preserves_weights(api):
    client, _ = api
    data = campaign(client).json()
    root = f"/api/campaigns/{data['id']}/streams"
    offers = f"{root}/{data['stream_id']}/offers"
    assert client.delete(offers + "/101").status_code == 409
    assert client.post(root + "/1/offers", json={"offer_id": 102}).status_code == 409
    for _ in range(2):
        response = client.post(offers, json={"offer_id": 102})
        assert response.status_code == 200
    assert response.json()[1]["offers"] == [
        {"offer_id": 101, "share": 100, "state": "active"},
        {"offer_id": 102, "share": 100, "state": "active"},
    ]
    response = client.delete(offers + "/102")
    assert response.status_code == 200
    assert response.json()[1]["offers"][0]["share"] == 100
    assert client.delete(offers + "/102").status_code == 404


def test_report_filters_dates_and_keeps_historical_offers(api):
    client, url = api
    data = campaign(client).json()
    campaign_id = data["id"]
    engine = create_engine(url)
    with Session(engine) as db, db.begin():
        db.add_all([
            DailyStat(campaign_id=campaign_id, offer_id=101, day=date(2026, 1, 2), clicks=80, conversions=16),
            DailyStat(campaign_id=campaign_id, offer_id=102, day=date(2026, 1, 2), clicks=20, conversions=1),
            DailyStat(campaign_id=campaign_id, offer_id=101, day=date(2026, 1, 1), clicks=100, conversions=1),
        ])
    engine.dispose()
    path = f"/api/campaigns/{campaign_id}/streams/{data['stream_id']}/stats"
    response = client.get(path, params={"start": "2026-01-02", "end": "2026-01-02"})
    assert response.status_code == 200
    assert response.json()["total"] == {"clicks": 100, "conversions": 17, "cr": 17.0}
    assert {row["offer_id"] for row in response.json()["rows"]} == {101, 102}
    empty = client.get(path, params={"start": "2026-02-01", "end": "2026-02-01"})
    assert empty.json()["total"] == {"clicks": 0, "conversions": 0, "cr": None}
    assert client.get(path, params={"start": "2026-01-03", "end": "2026-01-02"}).status_code == 422


def test_readonly_rejects_mutations_without_calling_tracker(tmp_path):
    settings = Settings(
        mode="readonly", keitaro_url="https://tracker.example",
        keitaro_api_key="dummy-key", database_url=f"sqlite:///{tmp_path / 'readonly.sqlite3'}",
    )
    with TestClient(create_app(settings)) as client:
        assert campaign(client).status_code == 403
        assert client.post("/api/campaigns/1/streams/2/offers", json={"offer_id": 3}).status_code == 403
        assert client.delete("/api/campaigns/1/streams/2/offers/3").status_code == 403
