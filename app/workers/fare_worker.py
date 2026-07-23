"""Scheduled fare ingestion + price-drop alert worker (APScheduler).

Runs inside its own container (see docker-compose 'worker' service) or
alongside the web app via start.sh on Railway.

Every POLL_MINUTES it:
  1. Refreshes FX rates (live, keyless API; falls back to cache).
  2. For each tracked route, determines which dates to fetch:
     - Specific-date subscriptions: fetch only that date.
     - Rolling-window subscriptions: sample dates every FARE_WINDOW_SAMPLE_DAYS
       within the next FARE_WINDOW_DAYS (default 30), NOT every single day.
       This avoids multiplying API calls 30x per route.
  3. Deduplicates: if multiple subscriptions on the same route want the same
     date, the ingestor is called once and the result is reused.
  4. Lets FareService detect drops and push WhatsApp alerts to subscribers.

Tuning knobs (env vars):
  FARE_POLL_MINUTES          - poll interval (default 5)
  FARE_WINDOW_DAYS           - rolling window length (default 30)
  FARE_WINDOW_SAMPLE_DAYS    - sample every N days within window (default 5)
  FARE_SOURCE                - mock|google|amadeus|hybrid (default mock)
"""
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("naijafly.fare_worker")

POLL_MINUTES = int(os.getenv("FARE_POLL_MINUTES", "5"))
FARE_WINDOW_DAYS = int(os.getenv("FARE_WINDOW_DAYS", "30"))
FARE_WINDOW_SAMPLE_DAYS = int(os.getenv("FARE_WINDOW_SAMPLE_DAYS", "5"))


def _get_sample_dates(window_days: int, step_days: int) -> List[datetime]:
    """Generate sample dates within the rolling window.

    Returns dates starting from tomorrow, stepping by step_days, covering
    the next window_days. Example with window=30, step=5:
    [day+1, day+6, day+11, day+16, day+21, day+26]
    """
    dates = []
    base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    current = base + timedelta(days=1)  # start from tomorrow
    end = base + timedelta(days=window_days)
    while current <= end:
        dates.append(current)
        current += timedelta(days=step_days)
    return dates


def _collect_dates_to_fetch(
    subscriptions, window_days: int, step_days: int
) -> Dict[int, Set[datetime]]:
    """Determine which (route_id, date) pairs to fetch this cycle.

    Groups subscriptions by route_id and collects:
    - Specific-date subs: just that date
    - Rolling-window subs: sampled dates within the window

    Returns: {route_id: {date1, date2, ...}}
    Deduplication is automatic via the set.
    """
    route_dates: Dict[int, Set[datetime]] = {}

    # Get the sample dates for rolling window (shared across all rolling subs)
    rolling_dates = _get_sample_dates(window_days, step_days)

    for sub in subscriptions:
        if sub.route_id is None:
            continue  # flight-only subscription, skip

        if sub.route_id not in route_dates:
            route_dates[sub.route_id] = set()

        if sub.target_date is not None:
            # Specific date subscription: only fetch that date
            route_dates[sub.route_id].add(sub.target_date)
        else:
            # Rolling window: add all sampled dates
            route_dates[sub.route_id].update(rolling_dates)

    return route_dates


def run_cycle(db=None, ingestor=None, notifier=None):
    """One ingestion+alert cycle. Injectable deps make this unit-testable."""
    from app.core.database import SessionLocal
    from app.models.models import Route, UserSubscription
    from app.services.fare_ingestor import get_active_ingestor
    from app.services.fare_service import FareService
    from app.services.notifier import get_notifier
    from app.utils.fx import FXService

    own_session = db is None
    db = db or SessionLocal()
    ingestor = ingestor or get_active_ingestor()
    notifier = notifier or get_notifier()
    try:
        fx = FXService(db)
        if fx.fetch_live_rates():
            logger.info("FX rates refreshed (live)")
        else:
            logger.info("FX live fetch failed - using cached/default rates")

        service = FareService(db, notifier=notifier)

        # Collect all subscriptions to determine what to fetch
        all_subs = db.query(UserSubscription).filter(
            UserSubscription.route_id.isnot(None)).all()

        # Get route_id -> dates mapping (deduped)
        route_dates = _collect_dates_to_fetch(
            all_subs, FARE_WINDOW_DAYS, FARE_WINDOW_SAMPLE_DAYS)

        # Also fetch for all seeded routes (even without subscribers) so
        # FARE queries return data immediately
        all_routes = db.query(Route).all()
        rolling_dates = _get_sample_dates(FARE_WINDOW_DAYS, FARE_WINDOW_SAMPLE_DAYS)
        for route in all_routes:
            if route.id not in route_dates:
                route_dates[route.id] = set()
            route_dates[route.id].update(rolling_dates)

        total_alerts = 0
        total_fares = 0
        for route_id, dates in route_dates.items():
            route = db.query(Route).get(route_id)
            if not route:
                continue
            route_fares = 0
            route_alerts = 0
            for travel_date in sorted(dates):
                fares = ingestor.fetch_fares(
                    route.origin, route.destination, travel_date)
                n = service.process_new_fares(route_id, fares)
                route_alerts += n
                route_fares += len(fares)
            total_alerts += route_alerts
            total_fares += route_fares
            logger.info(
                "Route %s->%s: %d date(s) sampled, %d fares, %d alerts",
                route.origin, route.destination, len(dates),
                route_fares, route_alerts)

        logger.info(
            "Cycle complete: %d routes, %d total fares, %d alerts pushed",
            len(route_dates), total_fares, total_alerts)
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

    # Seed Nigeria-domestic routes on first startup so the worker has routes to
    # ingest immediately, even before any user sends a SUBSCRIBE command.
    try:
        from app.seed_routes import seed
        new = seed()
        if new:
            logger.info("Seeded %d new Nigeria-domestic routes", new)
    except Exception as e:
        logger.warning("Route seeding skipped (non-fatal): %s", e)

    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, "interval", minutes=POLL_MINUTES,
                      next_run_time=datetime.now())
    logger.info(
        "Fare worker started. Poll=%dmin, window=%dd, sample every %dd, "
        "FARE_SOURCE=%s",
        POLL_MINUTES, FARE_WINDOW_DAYS, FARE_WINDOW_SAMPLE_DAYS,
        os.getenv("FARE_SOURCE", "mock"))
    scheduler.start()


if __name__ == "__main__":
    main()
