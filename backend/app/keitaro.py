from datetime import date
from hashlib import sha256
from typing import Any

import httpx

from .config import Settings
from .demo import PREFIX, DomainError, test_campaign_name
from .schemas import CreateCampaign
from .shares import normalize_shares, shares_with_new_offer


class TrackerError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class KeitaroClient:
    def __init__(self, settings: Settings):
        self.client = httpx.Client(
            base_url=settings.keitaro_url.rstrip("/") + "/admin_api/v1/",
            headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
            timeout=12.0,
            follow_redirects=False,
        )
        self.timezone = settings.timezone

    def _request(self, method: str, path: str, *, params=None, payload=None):
        try:
            response = self.client.request(method, path, params=params, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPStatusError as exc:
            raise TrackerError(f"Keitaro вернул HTTP {exc.response.status_code}") from None
        except (httpx.RequestError, ValueError):
            raise TrackerError("Keitaro недоступен или вернул некорректный ответ") from None

    def require_catalog(self, name: str, item_id: int):
        rows = self.catalog(name)
        if not any(row["id"] == item_id and row.get("state") != "deleted" for row in rows):
            raise DomainError(422, f"ID {item_id} отсутствует в справочнике {name}")

    def create_campaign(self, data: CreateCampaign) -> dict:
        for catalog, item_id in (
            ("domains", data.domain_id), ("groups", data.group_id),
            ("sources", data.source_id), ("offers", data.offer_id),
        ):
            if item_id is not None:
                self.require_catalog(catalog, item_id)

        name = test_campaign_name(data.name)
        alias = PREFIX + sha256(name.encode()).hexdigest()[:20]
        payload = {
            "alias": alias, "name": name, "state": "disabled", "type": "position",
            "group_id": str(data.group_id),
        }
        if data.domain_id is not None:
            payload["domain_id"] = data.domain_id
        if data.source_id is not None:
            payload["traffic_source_id"] = data.source_id
        campaign = self._request("POST", "campaigns", payload=payload)
        campaign_id = self._id(campaign)
        try:
            self._request("POST", "streams", payload={
                "campaign_id": campaign_id, "name": f"GEO {data.country} → Google",
                "type": "regular", "position": 1, "schema": "redirect", "action_type": "http",
                "action_payload": "https://www.google.com/", "collect_clicks": True,
                "filters": [{"name": "country", "mode": "accept", "payload": [data.country]}],
            })
            stream = self._request("POST", "streams", payload={
                "campaign_id": campaign_id, "name": "Офферы", "type": "default",
                "position": 2, "schema": "landings", "action_type": "http", "collect_clicks": True,
                "offers": [{"offer_id": data.offer_id, "share": 100, "state": "active"}],
            })
            stream_id = self._id(stream)
        except TrackerError:
            try:
                self._request("DELETE", f"campaigns/{campaign_id}")
            except TrackerError:
                raise TrackerError(
                    f"Не удалось настроить потоки. Проверьте выключенную кампанию #{campaign_id} в Keitaro."
                ) from None
            raise TrackerError("Не удалось настроить потоки. Кампания отправлена в архив.") from None
        return {"id": campaign_id, "name": name, "stream_id": stream_id}

    @staticmethod
    def _id(row) -> int:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1:
            raise TrackerError("Keitaro вернул неожиданный идентификатор")
        return row["id"]

    def campaign(self, campaign_id: int) -> dict:
        row = self._request("GET", f"campaigns/{campaign_id}")
        self._id(row)
        return row

    def change_offer(self, campaign_id: int, stream_id: int, offer_id: int, *, remove: bool):
        if not self.campaign(campaign_id)["name"].startswith(PREFIX):
            raise DomainError(403, f"Можно менять только кампании с префиксом {PREFIX}")
        stream = next((item for item in self.streams(campaign_id) if item["id"] == stream_id), None)
        if stream is None:
            raise DomainError(404, "Поток не найден в этой кампании")
        if stream.get("schema") != "landings" or stream.get("state") == "deleted":
            raise DomainError(409, "Офферы можно менять только в офферном потоке")

        links = [offer_link(row) for row in (stream.get("offers") or [])]
        if remove:
            remaining = [link for link in links if link["offer_id"] != offer_id]
            if len(remaining) == len(links):
                raise DomainError(404, "Оффер не привязан к потоку")
            if not remaining or (
                any(link["state"] == "active" for link in links)
                and not any(link["state"] == "active" for link in remaining)
            ):
                raise DomainError(409, "В потоке должен остаться хотя бы один активный оффер")
            links = remaining
            active = [link for link in links if link["state"] == "active"]
            shares = normalize_shares([link["share"] for link in active])
        else:
            if any(link["offer_id"] == offer_id for link in links):
                return
            self.require_catalog("offers", offer_id)
            active = [link for link in links if link["state"] == "active"]
            shares = shares_with_new_offer([link["share"] for link in active])
            new_link = {"offer_id": offer_id, "share": 0, "state": "active"}
            links.append(new_link)
            active.append(new_link)

        for link, share in zip(active, shares, strict=True):
            link["share"] = share

        self._request("PUT", f"streams/{stream_id}", payload={"offers": links})

    def catalog(self, name: str) -> list[dict]:
        paths = {"offers": "offers", "domains": "domains", "groups": "groups", "sources": "traffic_sources"}
        rows = self._request("GET", paths[name], params={"type": "campaigns"} if name == "groups" else None)
        return self._list(rows)

    def campaigns(self, offset: int, limit: int) -> list[dict]:
        return self._list(self._request("GET", "campaigns", params={"offset": offset, "limit": limit}))

    def streams(self, campaign_id: int) -> list[dict]:
        return self._list(self._request("GET", f"campaigns/{campaign_id}/streams"))

    def stats(self, campaign_id: int, stream_id: int, start: date, end: date) -> list[dict]:
        report = self._request("POST", "report/build", payload={
            "range": {"from": str(start), "to": str(end), "timezone": self.timezone},
            "dimensions": ["offer_id"],
            "measures": ["clicks", "conversions"],
            "filters": [
                {"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id},
                {"name": "stream_id", "operator": "EQUALS", "expression": stream_id},
            ],
        })
        if not isinstance(report, dict):
            raise TrackerError("Неверный формат отчёта Keitaro")
        return self._list(report.get("rows"))

    @staticmethod
    def _list(data) -> list[dict]:
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise TrackerError("Keitaro вернул данные в неожиданном формате")
        return data


def offer_link(row: dict) -> dict:
    return {"offer_id": row["offer_id"], "share": row["share"], "state": row.get("state", "active")}
