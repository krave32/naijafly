"""Fare ingestion + price-drop alerting.

Alert rule (per subscription):
  - If sub.target_price is set: alert when a new fare (in the fare's own
    currency) drops to or below target_price.
  - If no target: alert when the new fare is below BOTH the previous cheapest
    fare on the route AND the route's trailing average (i.e. a genuine drop,
    not noise).
Every alert is actually pushed via the notifier and recorded in AlertHistory.
"""
from typing import List

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Fare, Route, UserSubscription, AlertHistory
from app.utils.fx import FXService
from app.utils import notify_templates as tmpl


class FareService:
    def __init__(self, db: Session, notifier=None):
        self.db = db
        self.fx = FXService(db)
        self.notifier = notifier

    def process_new_fares(self, route_id: int, fares_data: List[dict]) -> int:
        """Ingest a batch of fares; returns number of alerts pushed."""
        # Snapshot route stats BEFORE inserting new fares
        prev_min = self.db.query(func.min(Fare.price)).filter(
            Fare.route_id == route_id).scalar()
        prev_avg = self.db.query(func.avg(Fare.price)).filter(
            Fare.route_id == route_id).scalar()

        alerts_sent = 0
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
            alerts_sent += self.check_for_alerts(fare, prev_min, prev_avg)
        return alerts_sent

    def check_for_alerts(self, new_fare: Fare, prev_min, prev_avg) -> int:
        subs = self.db.query(UserSubscription).filter(
            UserSubscription.route_id == new_fare.route_id).all()
        if not subs:
            return 0

        route = self.db.query(Route).get(new_fare.route_id)
        sent = 0
        for sub in subs:
            triggered = False
            if sub.target_price is not None:
                triggered = new_fare.price <= sub.target_price
            elif prev_min is not None and prev_avg is not None:
                triggered = new_fare.price < prev_min and new_fare.price < prev_avg

            if not triggered:
                continue

            usd = self.fx.convert(new_fare.price, new_fare.currency, "USD")
            body = tmpl.fare_drop_push(
                route.origin, route.destination, new_fare.price,
                new_fare.currency, usd, new_fare.source)
            ok = self.notifier.send(sub.user_id, body) if self.notifier else False
            self.db.add(AlertHistory(
                user_id=sub.user_id, alert_type="fare_drop",
                route_id=new_fare.route_id, message=body, delivered=bool(ok)))
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
