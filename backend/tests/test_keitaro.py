import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.keitaro import KeitaroClient, TrackerError
from app.main import create_app
from app.schemas import CreateCampaign


def test_report_uses_read_endpoint_and_scopes_filters():
    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert request.url.path == "/admin_api/v1/report/build"
        assert request.headers["Api-Key"] == "test-only"
        body = json.loads(request.content)
        assert body["range"] == {"from": "2026-01-01", "to": "2026-01-03", "timezone": "Europe/Moscow"}
        assert body["dimensions"] == ["offer_id"]
        assert body["measures"] == ["clicks", "conversions"]
        assert body["filters"] == [
            {"name": "campaign_id", "operator": "EQUALS", "expression": 15},
            {"name": "stream_id", "operator": "EQUALS", "expression": 20},
        ]
        return httpx.Response(200, json={"rows": [{"offer_id": "1", "clicks": "20", "conversions": "2"}]})

    tracker = KeitaroClient(Settings(
        mode="readonly", keitaro_url="https://tracker.example", keitaro_api_key="test-only",
    ))
    tracker.client.close()
    with httpx.Client(
        base_url="https://tracker.example/admin_api/v1/", headers={"Api-Key": "test-only"},
        transport=httpx.MockTransport(handler),
    ) as client:
        tracker.client = client
        assert tracker.stats(15, 20, date(2026, 1, 1), date(2026, 1, 3)) == [
            {"offer_id": "1", "clicks": "20", "conversions": "2"},
        ]


def test_keitaro_campaign_and_offer_editor(monkeypatch):
    campaigns = {21: {"id": 21, "name": "unrelated"}}
    streams = {}

    def handler(request: httpx.Request):
        path = request.url.path.removeprefix("/admin_api/v1/")
        method = request.method
        if method == "GET" and path in ("domains", "groups", "traffic_sources", "offers"):
            ids = [101, 102] if path == "offers" else [1]
            return httpx.Response(200, json=[{"id": n, "name": path} for n in ids])
        if method == "POST" and path == "campaigns":
            body = json.loads(request.content)
            assert body["state"] == "disabled"
            assert body["name"] == "test_kalinin_smoke"
            assert (body["domain_id"], body["group_id"], body["traffic_source_id"]) == (1, "1", 1)
            campaigns[22] = {"id": 22, **body}
            return httpx.Response(200, json=campaigns[22])
        if method == "POST" and path == "streams":
            body = json.loads(request.content)
            stream_id = 50 + len(streams)
            assert body["campaign_id"] == 22
            if stream_id == 50:
                assert body["type"] == "regular"
                assert body["action_payload"] == "https://www.google.com/"
                assert body["filters"] == [{"name": "country", "mode": "accept", "payload": ["DE"]}]
            else:
                assert body["type"] == "default"
                assert body["offers"][0]["offer_id"] == 101
                body["offers"][0]["share"] = 42
            streams[stream_id] = {"id": stream_id, **body}
            return httpx.Response(200, json=streams[stream_id])
        if method == "GET" and path in ("campaigns/21", "campaigns/22"):
            return httpx.Response(200, json=campaigns[int(path.split("/")[-1])])
        if method == "GET" and path == "campaigns/22/streams":
            return httpx.Response(200, json=list(streams.values()))
        if method == "PUT" and path == "streams/51":
            body = json.loads(request.content)
            assert list(body) == ["offers"]
            streams[51].update(body)
            return httpx.Response(200, json=streams[51])
        raise AssertionError(f"Unexpected {method} {path}")

    original_client = httpx.Client

    def tracker_client(**options):
        return original_client(transport=httpx.MockTransport(handler), **options)

    with monkeypatch.context() as patch:
        patch.setattr("app.keitaro.httpx.Client", tracker_client)
        app = create_app(Settings(
            mode="keitaro", keitaro_url="https://tracker.example", keitaro_api_key="test-only",
        ))

    with TestClient(app) as client:
        response = client.post("/api/campaigns", json={
            "name": "smoke", "country": "DE", "domain_id": 1, "group_id": 1,
            "source_id": 1, "offer_id": 101,
        })
        assert response.status_code == 201
        assert response.json()["stream_id"] == 51

        path = "/api/campaigns/22/streams/51/offers"
        assert client.delete(path + "/101").status_code == 409
        assert client.post(path.replace("/22/", "/21/"), json={"offer_id": 102}).status_code == 403
        assert client.post(path.replace("/51/", "/50/"), json={"offer_id": 102}).status_code == 409
        for _ in range(2):
            response = client.post(path, json={"offer_id": 102})
            assert response.status_code == 200
        assert response.json()[1]["offers"] == [
            {"offer_id": 101, "share": 42, "state": "active"},
            {"offer_id": 102, "share": 100, "state": "active"},
        ]
        assert client.delete(path + "/102").status_code == 200
        assert streams[51]["offers"] == [{"offer_id": 101, "share": 42, "state": "active"}]


def test_keitaro_archives_partial_campaign():
    requests = []

    def handler(request: httpx.Request):
        path = request.url.path.removeprefix("/admin_api/v1/")
        requests.append((request.method, path))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 1}])
        if path == "campaigns":
            return httpx.Response(200, json={"id": 22})
        if path == "streams":
            return httpx.Response(406)
        if request.method == "DELETE" and path == "campaigns/22":
            return httpx.Response(201)
        raise AssertionError(path)

    tracker = KeitaroClient(Settings(
        mode="keitaro", keitaro_url="https://tracker.example", keitaro_api_key="test-only",
    ))
    tracker.client.close()
    with httpx.Client(
        base_url="https://tracker.example/admin_api/v1/", transport=httpx.MockTransport(handler),
    ) as tracker.client:
        with pytest.raises(TrackerError, match="отправлена в архив"):
            tracker.create_campaign(CreateCampaign(
                name="smoke", country="DE", domain_id=1, group_id=1, source_id=1, offer_id=1,
            ))
    assert requests[-3:] == [("POST", "campaigns"), ("POST", "streams"), ("DELETE", "campaigns/22")]
