"""Scheduled fare ingestion + price-drop alert worker (APScheduler).

Runs inside its own container (see docker-compose 'worker' service).
Every POLL_MINUTES it:
  1. refreshes FX rates (live, keyless API; falls back to cache),
  2. pulls fares for every tracked route from the active ingestor
     (MockFareIngestor today; swap-in point for a scraper later),
  3. lets FareService detect drops and PUSH WhatsApp alerts to subscribers.
"""
import logging
import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("naijafly.fare_worker")

POLL_MINUTES = int(os.getenv("FARE_POLL_MINUTES", "15"))


def run_cycle(db=None, ingestor=None, notifier=None):
    """One ingestion+alert cycle. Injectable deps make this unit-testable."""
    from app.core.database import SessionLocal
    from app.models.models import Route
    from app.services.fare_ingestor import get_active_ingestor
    from app.services.fare_service import FareService
    from app.services.notifier import get_notifier
    from app.utils.fx import FXService

    own_session = db is None
    db = db or SessionLocal()
    # Reads FARE_SOURCE env var (mock|amadeus|google|hybrid) - no code change needed to switch.
    ingestor = ingestor or get_active_ingestor()
    notifier = notifier or get_notifier()
    try:
        fx = FXService(db)
        if fx.fetch_live_rates():
            logger.info("FX rates refreshed (live)")
        else:
            logger.info("FX live fetch failed - using cached/default rates")

        service = FareService(db, notifier=notifier)
        routes = db.query(Route).all()
        total_alerts = 0
        for route in routes:
            travel_date = datetime.utcnow() + timedelta(days=14)
            fares = ingestor.fetch_fares(route.origin, route.destination, travel_date)
            n = service.process_new_fares(route.id, fares)
            total_alerts += n
            logger.info("Route %s->%s: %d fares ingested, %d alerts pushed",
                        route.origin, route.destination, len(fares), n)
        return total_alerts
    finally:
        if own_session:
            db.close()


def main():
    # Wait for DB, then create tables if API hasn't yet
    from app.core.database import engine
    from app.models.models import Base
    for _ in range(30):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except Exception:
            logger.info("Waiting for database...")
            time.sleep(2)

    # Seed West African routes on first startup so the worker has routes to
    # ingest immediately, even before any user sends a SUBSCRIBE command.
    try:
        from app.seed_routes import seed
        new = seed()
        if new:
            logger.info("Seeded %d new West African routes", new)
    except Exception as e:
        logger.warning("Route seeding skipped (non-fatal): %s", e)

    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, "interval", minutes=POLL_MINUTES,
                      next_run_time=datetime.now())
    logger.info("Fare worker started, polling every %d min, FARE_SOURCE=%s",
                POLL_MINUTES, os.getenv("FARE_SOURCE", "mock"))
    scheduler.start()


if __name__ == "__main__":
    main()
