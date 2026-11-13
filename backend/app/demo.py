from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Campaign, DailyStat, StreamOffer
from .schemas import CreateCampaign
from .shares import normalize_shares, shares_with_new_offer

CATALOGS = {
    "domains": [{"id": 1, "name": "tracker.demo.example"}],
    "groups": [{"id": 1, "name": "Тестовые кампании"}],
    "sources": [{"id": 1, "name": "Демо-источник"}],
    "offers": [
        {"id": 101, "name": "Пробная подписка"},
        {"id": 102, "name": "Заявка на консультацию"},
        {"id": 103, "name": "Демо-регистрация"},
    ],
}
PREFIX = "test_kalinin_"
OFFER_STREAM = 2


class DomainError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def test_campaign_name(name: str) -> str:
    name = name if name.startswith(PREFIX) else PREFIX + name
    if name == PREFIX:
        raise DomainError(422, "Укажите название после префикса")
    return name


def require_catalog(name: str, item_id: int):
    if not any(row["id"] == item_id for row in CATALOGS[name]):
        raise DomainError(422, f"ID {item_id} отсутствует в справочнике {name}")


def create_campaign(db: Session, data: CreateCampaign) -> Campaign:
    if data.domain_id is None or data.source_id is None:
        raise DomainError(422, "В деморежиме выберите домен и источник")
    for catalog, item_id in (
        ("offers", data.offer_id), ("domains", data.domain_id),
        ("groups", data.group_id), ("sources", data.source_id),
    ):
        require_catalog(catalog, item_id)
    name = test_campaign_name(data.name)
    if db.scalar(select(Campaign.id).where(Campaign.name == name)) is not None:
        raise DomainError(409, "Кампания с таким названием уже существует")

    campaign = Campaign(
        name=name, country=data.country, domain_id=data.domain_id,
        group_id=data.group_id, source_id=data.source_id,
    )
    db.add(campaign)
    db.flush()
    db.add(StreamOffer(campaign_id=campaign.id, offer_id=data.offer_id, share=100))
    return campaign


def get_campaign(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise DomainError(404, "Кампания не найдена")
    return campaign


def offer_links(db: Session, campaign_id: int) -> list[StreamOffer]:
    return list(db.scalars(
        select(StreamOffer)
        .where(StreamOffer.campaign_id == campaign_id)
        .order_by(StreamOffer.offer_id)
    ))


def streams(db: Session, campaign: Campaign) -> list[dict]:
    return [
        {"id": 1, "name": f"GEO {campaign.country} → Google (симуляция)", "editable": False, "offers": []},
        {
            "id": OFFER_STREAM, "name": "Офферы", "editable": True,
            "offers": [
                {"offer_id": row.offer_id, "share": row.share, "state": "active"}
                for row in offer_links(db, campaign.id)
            ],
        },
    ]


def change_offer(db: Session, campaign_id: int, stream_id: int, offer_id: int, *, remove: bool):
    get_campaign(db, campaign_id)
    if stream_id != OFFER_STREAM:
        raise DomainError(409, "Офферы можно менять только в офферном потоке")
    links = offer_links(db, campaign_id)
    match = next((link for link in links if link.offer_id == offer_id), None)
    if remove:
        if match is None:
            raise DomainError(404, "Оффер не привязан к потоку")
        if len(links) == 1:
            raise DomainError(409, "В потоке должен остаться хотя бы один оффер")
        db.delete(match)
        links.remove(match)
        shares = normalize_shares([link.share for link in links])
    else:
        require_catalog("offers", offer_id)
        if match is not None:
            return
        shares = shares_with_new_offer([link.share for link in links])
        new_link = StreamOffer(campaign_id=campaign_id, offer_id=offer_id)
        db.add(new_link)
        links.append(new_link)

    for link, share in zip(links, shares, strict=True):
        link.share = share


def stats(db: Session, campaign_id: int, start: date, end: date) -> list[dict]:
    rows = db.execute(
        select(DailyStat.offer_id, func.sum(DailyStat.clicks), func.sum(DailyStat.conversions))
        .where(DailyStat.campaign_id == campaign_id, DailyStat.day.between(start, end))
        .group_by(DailyStat.offer_id)
    )
    return [{"offer_id": offer_id, "clicks": clicks, "conversions": conversions}
            for offer_id, clicks, conversions in rows]
