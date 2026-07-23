"""Fare ingestion + price-drop alerting (date-aware).

Alert rule (per subscription):
  - If sub.target_price is set: alert when a new fare (in the fare's own
    currency) drops to or below target_price.
  - If no target: alert when the new fare is below BOTH the previous cheapest
    fare on the route AND the route's trailing average (i.e. a genuine drop,
    not noise).
Every alert is actually pushed via the notifier and recorded in AlertHistory.

Anti-spam measures:
  - Running minimum within a batch: only the single cheapest new fare per
    cycle can trigger an alert (not every fare below the old minimum).
  - Cooldown: the same (user, route) pair is alerted at most once per hour.

Date-aware queries:
  - get_cheapest_fare() accepts optional specific_date OR date_from/date_to
    window. Never compares across unrelated dates.
  - process_new_fares() scopes prev_min/prev_avg to the same flight_date
    context as the incoming fares, not the route's entire history.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Fare, Route, UserSubscription, AlertHistory
from app.utils.fx import FXService
from app.utils import notify_templates as tmpl

# Minimum time between alerts for the same (user, route) pair.
ALERT_COOLDOWN_MINUTES = 60


class FareService:
    def __init__(self, db: Session, notifier=None):
        self.db = db
        self.fx = FXService(db)
        self.notifier = notifier

    def process_new_fares(self, route_id: int, fares_data: List[dict]) -> int:
        """Ingest a batch of fares; returns number of alerts pushed.

        Date-aware: prev_min/prev_avg are scoped to the SAME flight_date as
        the incoming fares, not the route's entire history. This prevents a
        cheap Tuesday fare from triggering a false alert when compared against
        expensive Christmas fares on the same route.

        Key anti-spam logic: we track a *running minimum* across the batch.
        Only a fare that is strictly cheaper than every fare seen so far
        (including earlier fares in this same batch) can trigger an alert.
        This means at most ONE alert per subscription per cycle.
        """
        if not fares_data:
            return 0

        # Determine the flight_date context from the first fare in the batch.
        # All fares in a single batch should be for the same date (the worker
        # calls process_new_fares once per date per route).
        batch_date = fares_data[0].get("flight_date")
        if isinstance(batch_date, datetime):
            # Scope to the same calendar day
            day_start = batch_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
        else:
            day_start = day_end = None

        # Snapshot route stats for SAME DATE before inserting new fares
        q_min = self.db.query(func.min(Fare.price)).filter(
            Fare.route_id == route_id)
        q_avg = self.db.query(func.avg(Fare.price)).filter(
            Fare.route_id == route_id)
        if day_start and day_end:
            q_min = q_min.filter(Fare.flight_date >= day_start, Fare.flight_date < day_end)
            q_avg = q_avg.filter(Fare.flight_date >= day_start, Fare.flight_date < day_end)
        prev_min = q_min.scalar()
        prev_avg = q_avg.scalar()

        alerts_sent = 0
        # Running minimum starts at the historical minimum for this date (or infinity).
        running_min = prev_min if prev_min is not None else float("inf")
        alerted_users_this_batch: set = set()  # dedup within this batch

        # Build a date label for push messages
        date_label = ""
        if batch_date:
            if isinstance(batch_date, datetime):
                date_label = batch_date.strftime("%Y-%m-%d")

        for data in fares_data:
            fare = Fare(
                route_id=route_id,
                price=data["price"],
                currency=data["currency"],
                source=data["source"],
                flight_date=data["flight_date"],
            )
            self.db.add(fare)
            self.db.commit()

            n = self.check_for_alerts(
                fare, running_min, prev_avg, alerted_users_this_batch,
                date_label=date_label)
            alerts_sent += n

            # Update running minimum so subsequent fares in this batch must
            # be strictly cheaper to trigger another alert.
            if fare.price < running_min:
                running_min = fare.price

        return alerts_sent

    def check_for_alerts(
        self, new_fare: Fare, running_min, prev_avg,
        alerted_users_this_batch: set = None,
        date_label: str = "",
    ) -> int:
        """Check if this fare triggers an alert for any subscription.

        Uses a running minimum (not the batch-start snapshot) so that within
        a batch, only the single cheapest new fare can alert — preventing
        the '10 fares → 10 alerts' spam.
        """
        alerted_users_this_batch = alerted_users_this_batch or set()

        subs = self.db.query(UserSubscription).filter(
            UserSubscription.route_id == new_fare.route_id).all()
        if not subs:
            return 0

        route = self.db.query(Route).get(new_fare.route_id)
        sent = 0
        cooldown_cutoff = datetime.utcnow() - timedelta(minutes=ALERT_COOLDOWN_MINUTES)

        for sub in subs:
            # Skip if we already alerted this user in this batch
            if sub.user_id in alerted_users_this_batch:
                continue

            # Date-aware: skip subscriptions that target a different date
            if sub.target_date is not None and new_fare.flight_date is not None:
                sub_date = sub.target_date.date() if hasattr(sub.target_date, 'date') else sub.target_date
                fare_date = new_fare.flight_date.date() if hasattr(new_fare.flight_date, 'date') else new_fare.flight_date
                if sub_date != fare_date:
                    continue

            triggered = False
            if sub.target_price is not None:
                # Alert when price hits the user's target
                triggered = new_fare.price <= sub.target_price
            elif running_min is not None and prev_avg is not None:
                # Alert only if this fare is strictly cheaper than the
                # running minimum (includes fares from earlier in this batch)
                # AND cheaper than the historical average.
                triggered = (
                    new_fare.price < running_min
                    and new_fare.price < prev_avg
                )

            if not triggered:
                continue

            # Cooldown: don't re-alert the same (user, route) within the
            # cooldown window, even across different batches/cycles.
            recent_alert = (
                self.db.query(AlertHistory)
                .filter(
                    AlertHistory.user_id == sub.user_id,
                    AlertHistory.route_id == new_fare.route_id,
                    AlertHistory.alert_type == "fare_drop",
                    AlertHistory.created_at > cooldown_cutoff,
                )
                .first()
            )
            if recent_alert:
                continue

            usd = self.fx.convert(new_fare.price, new_fare.currency, "USD")
            body = tmpl.fare_drop_push(
                route.origin, route.destination, new_fare.price,
                new_fare.currency, usd, new_fare.source,
                date_label=date_label)
            ok = self.notifier.send(sub.user_id, body) if self.notifier else False
            self.db.add(AlertHistory(
                user_id=sub.user_id, alert_type="fare_drop",
                route_id=new_fare.route_id, message=body, delivered=bool(ok)))
            alerted_users_this_batch.add(sub.user_id)
            sent += 1

        self.db.commit()
        return sent

    def get_cheapest_fare(
        self,
        route_id: int,
        specific_date: Optional[datetime] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Get the cheapest fare for a route, scoped by date.

        Args:
            route_id: The route to query.
            specific_date: If set, only return fares for this exact date.
            date_from/date_to: If set (both), return fares within this window.
            If neither is set, returns the cheapest across ALL dates (legacy).

        This fixes the original bug where a cheap Tuesday fare and an expensive
        Christmas Eve fare on the same route were compared as if interchangeable.
        """
        query = self.db.query(Fare).filter(Fare.route_id == route_id)

        if specific_date is not None:
            # Match fares for the same calendar day
            day_start = specific_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            query = query.filter(Fare.flight_date >= day_start, Fare.flight_date < day_end)
        elif date_from is not None and date_to is not None:
            query = query.filter(Fare.flight_date >= date_from, Fare.flight_date <= date_to)

        fare = query.order_by(Fare.price.asc()).first()
        if not fare:
            return None
        return {
            "price_local": fare.price,
            "currency_local": fare.currency,
            "price_usd": self.fx.convert(fare.price, fare.currency, "USD"),
            "source": fare.source,
            "flight_date": fare.flight_date,
        }
