"""Добавляет одну кампанию с вымышленными данными для демонстрации."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .config import Settings
from .demo import PREFIX, create_campaign
from .models import Campaign, DailyStat, StreamOffer
from .schemas import CreateCampaign


def main():
    settings = Settings()
    if settings.mode != "demo":
        raise SystemExit("Демо-данные доступны только в режиме demo")
    engine = create_engine(settings.database_url)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    with Session(engine) as db, db.begin():
        if db.scalar(select(Campaign.id).where(Campaign.name == PREFIX + "demo")):
            print("Демо-кампания уже существует")
            return
        campaign = create_campaign(db, CreateCampaign(
            name="demo", country="DE", offer_id=101, domain_id=1, group_id=1, source_id=1,
        ))
        db.add(StreamOffer(campaign_id=campaign.id, offer_id=102, share=100))
        for offset in range(7):
            for offer_id, clicks, conversions in [(101, 144, 12), (102, 80, 5)]:
                db.add(DailyStat(
                    campaign_id=campaign.id, offer_id=offer_id, day=today - timedelta(days=offset),
                    clicks=clicks - offset * 4, conversions=conversions - offset // 2,
                ))
        print("Добавлена демо-кампания с вымышленной статистикой")


if __name__ == "__main__":
    main()
