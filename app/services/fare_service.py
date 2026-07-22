"""Fare ingestion + price-drop alerting.

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
"""
from datetime import datetime, timedelta
from typing import List

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

        Key anti-spam logic: we track a *running minimum* across the batch.
        Only a fare that is strictly cheaper than every fare seen so far
        (including earlier fares in this same batch) can trigger an alert.
        This means at most ONE alert per subscription per cycle.
        """
        # Snapshot route stats BEFORE inserting new fares
        prev_min = self.db.query(func.min(Fare.price)).filter(
            Fare.route_id == route_id).scalar()
        prev_avg = self.db.query(func.avg(Fare.price)).filter(
            Fare.route_id == route_id).scalar()

        alerts_sent = 0
        # Running minimum starts at the historical minimum (or infinity).
        running_min = prev_min if prev_min is not None else float("inf")
        alerted_users_this_batch: set = set()  # dedup within this batch

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
                fare, running_min, prev_avg, alerted_users_this_batch)
            alerts_sent += n

            # Update running minimum so subsequent fares in this batch must
            # be strictly cheaper to trigger another alert.
            if fare.price < running_min:
                running_min = fare.price

        return alerts_sent

    def check_for_alerts(
        self, new_fare: Fare, running_min, prev_avg,
        alerted_users_this_batch: set = None,
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
                new_fare.currency, usd, new_fare.source)
            ok = self.notifier.send(sub.user_id, body) if self.notifier else False
            self.db.add(AlertHistory(
                user_id=sub.user_id, alert_type="fare_drop",
                route_id=new_fare.route_id, message=body, delivered=bool(ok)))
            alerted_users_this_batch.add(sub.user_id)
            sent += 1

        self.db.commit()
        return sent

    def get_cheapest_fare(self, route_id: int):
        fare = (self.db.query(Fare)
                .filter(Fare.route_id == route_id)
                .order_by(Fare.price.asc())
                .first())
        if not fare:
            return None
        return {
            "price_local": fare.price,
            "currency_local": fare.currency,
            "price_usd": self.fx.convert(fare.price, fare.currency, "USD"),
            "source": fare.source,
        }
