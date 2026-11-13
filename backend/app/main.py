from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Path as ApiPath, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import demo
from .config import Settings
from .keitaro import KeitaroClient, TrackerError, offer_link
from .models import Campaign
from .schemas import AddOffer, CreateCampaign

Id = Annotated[int, ApiPath(gt=0)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url)
    tracker = KeitaroClient(settings) if settings.mode != "demo" else None
    tracker_write_lock = Lock()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            if tracker:
                tracker.client.close()
            engine.dispose()

    app = FastAPI(title="AdrobotTask", lifespan=lifespan)

    def session():
        with Session(engine) as db:
            yield db

    def write_session():
        with Session(engine) as db:
            if not tracker and engine.dialect.name == "sqlite":
                # Serialize read-modify-write across concurrent SQLite requests.
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield db

    def require_writes():
        if settings.mode == "readonly":
            raise demo.DomainError(403, "Изменения отключены в режиме чтения")

    @app.exception_handler(demo.DomainError)
    async def domain_error(_request: Request, exc: demo.DomainError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(TrackerError)
    async def tracker_error(_request: Request, exc: TrackerError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(IntegrityError)
    async def conflict(_request: Request, _exc: IntegrityError):
        return JSONResponse({"detail": "Конфликт записи. Обновите данные и повторите попытку."}, status_code=409)

    @app.get("/api/config")
    def config():
        return {
            "mode": settings.mode, "timezone": settings.timezone,
            "today": datetime.now(ZoneInfo(settings.timezone)).date(),
            "prefix": demo.PREFIX,
        }

    @app.get("/api/catalogs/{name}")
    def catalog(name: Literal["offers", "domains", "groups", "sources"]):
        rows = tracker.catalog(name) if tracker else demo.CATALOGS[name]
        return [{"id": row["id"], "name": row["name"]} for row in rows if row.get("state") != "deleted"]

    @app.get("/api/campaigns")
    def campaigns(
        offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(session),
    ):
        rows = (
            tracker.campaigns(offset, limit) if tracker else [
                {"id": row.id, "name": row.name}
                for row in db.scalars(select(Campaign).order_by(Campaign.id).offset(offset).limit(limit))
            ]
        )
        return [{"id": row["id"], "name": row["name"]} for row in rows]

    @app.post("/api/campaigns", status_code=201, dependencies=[Depends(require_writes)])
    def create(data: CreateCampaign, db: Session = Depends(write_session)):
        if tracker:
            with tracker_write_lock:
                return tracker.create_campaign(data)
        campaign = demo.create_campaign(db, data)
        result = {"id": campaign.id, "name": campaign.name, "stream_id": demo.OFFER_STREAM}
        db.commit()
        return result

    def campaign_streams(db: Session, campaign_id: int):
        if not tracker:
            return demo.streams(db, demo.get_campaign(db, campaign_id))
        writable = settings.mode == "keitaro" and tracker.campaign(campaign_id)["name"].startswith(demo.PREFIX)
        return [
            {
                "id": row["id"], "name": row["name"],
                "editable": writable and row.get("schema") == "landings" and row.get("state") != "deleted",
                "offers": [offer_link(link) for link in (row.get("offers") or [])],
            }
            for row in tracker.streams(campaign_id)
        ]

    @app.get("/api/campaigns/{campaign_id}/streams")
    def streams(campaign_id: Id, db: Session = Depends(session)):
        return campaign_streams(db, campaign_id)

    def modify(db: Session, campaign_id: int, stream_id: int, offer_id: int, *, remove: bool):
        if tracker:
            with tracker_write_lock:
                tracker.change_offer(campaign_id, stream_id, offer_id, remove=remove)
                return campaign_streams(db, campaign_id)
        demo.change_offer(db, campaign_id, stream_id, offer_id, remove=remove)
        db.commit()
        return campaign_streams(db, campaign_id)

    @app.post("/api/campaigns/{campaign_id}/streams/{stream_id}/offers", dependencies=[Depends(require_writes)])
    def add(campaign_id: Id, stream_id: Id, data: AddOffer, db: Session = Depends(write_session)):
        return modify(db, campaign_id, stream_id, data.offer_id, remove=False)

    @app.delete("/api/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}", dependencies=[Depends(require_writes)])
    def remove(campaign_id: Id, stream_id: Id, offer_id: Id, db: Session = Depends(write_session)):
        return modify(db, campaign_id, stream_id, offer_id, remove=True)

    @app.get("/api/campaigns/{campaign_id}/streams/{stream_id}/stats")
    def stats(campaign_id: Id, stream_id: Id, start: date, end: date, db: Session = Depends(session)):
        if end < start or (end - start).days > 365:
            raise demo.DomainError(422, "Выберите корректный период до 366 дней")
        stream = next((s for s in campaign_streams(db, campaign_id) if s["id"] == stream_id), None)
        if stream is None:
            raise demo.DomainError(404, "Поток не найден")
        rows = (
            tracker.stats(campaign_id, stream_id, start, end) if tracker
            else demo.stats(db, campaign_id, start, end) if stream_id == demo.OFFER_STREAM else []
        )
        return format_report(rows, stream["offers"])

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def format_report(rows: list[dict], links: list[dict]):
    counts: dict[int, list[int]] = {int(link["offer_id"]): [0, 0] for link in links}
    try:
        for row in rows:
            offer_id = int(row["offer_id"] or 0)
            if offer_id <= 0:
                continue
            clicks, conversions = int(row["clicks"]), int(row["conversions"])
            if min(clicks, conversions) < 0:
                raise ValueError("negative statistic")
            current = counts.setdefault(offer_id, [0, 0])
            current[0] += clicks
            current[1] += conversions
    except (KeyError, TypeError, ValueError):
        raise TrackerError("В отчёте Keitaro нет ожидаемых числовых полей") from None

    def metrics(clicks: int, conversions: int):
        return {"clicks": clicks, "conversions": conversions,
                "cr": round(conversions / clicks * 100, 2) if clicks else None}

    return {
        "rows": [{"offer_id": key, **metrics(*value)} for key, value in sorted(counts.items())],
        "total": metrics(sum(v[0] for v in counts.values()), sum(v[1] for v in counts.values())),
    }


app = create_app()
