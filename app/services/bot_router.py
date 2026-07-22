"""Inbound WhatsApp command router.

Commands (case-insensitive):
  SUBSCRIBE LOS ACC [80000]   -> fare-drop subscription for route (optional target price)
  FARE LOS ACC                -> current cheapest fare, local + USD
  TRACK P47123 2026-07-20     -> subscribe to a specific flight's status pushes
  <anything else while tracking a flight> -> treated as a status report
  HELP                        -> command list

Returns the reply text to send back. All DB access goes through the session
passed in, so the router is fully unit-testable without HTTP or Twilio.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import Route, Flight, UserSubscription, StatusType
from app.services.fare_service import FareService
from app.services.status_service import StatusAggregationService
from app.utils.parser import MessageParser
from app.utils import notify_templates as tmpl

HELP_TEXT = (
    "NaijaFly commands:\n"
    "SUBSCRIBE <FROM> <TO> [target price] - fare drop alerts (e.g. SUBSCRIBE LOS ACC 80000)\n"
    "FARE <FROM> <TO> - current cheapest fare\n"
    "TRACK <FLIGHT> <YYYY-MM-DD> - live boarding updates (e.g. TRACK P47123 2026-07-20)\n"
    "While tracking, just text what you see: 'boarding now gate 12', '2hr delay announced'\n"
    "HELP - this message"
)


class BotRouter:
    def __init__(self, db: Session, notifier=None):
        self.db = db
        self.notifier = notifier
        self.fare_service = FareService(db)
        self.status_service = StatusAggregationService(db, notifier=notifier)

    def handle(self, user_id: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return HELP_TEXT
        parts = text.split()
        cmd = parts[0].upper()

        if cmd == "HELP":
            return HELP_TEXT
        if cmd == "SUBSCRIBE" and len(parts) >= 3:
            return self._subscribe_route(user_id, parts[1], parts[2],
                                         float(parts[3]) if len(parts) > 3 else None)
        if cmd == "FARE" and len(parts) >= 3:
            return self._fare_query(parts[1], parts[2])
        if cmd == "TRACK" and len(parts) >= 2:
            date_str = parts[2] if len(parts) > 2 else None
            return self._track_flight(user_id, parts[1], date_str)

        # Not a command: if the user tracks any flight, treat as a status report
        return self._maybe_status_report(user_id, text)

    # ---- handlers ----

    def _get_or_create_route(self, origin: str, dest: str) -> Route:
        origin, dest = origin.upper(), dest.upper()
        route = self.db.query(Route).filter_by(origin=origin, destination=dest).first()
        if not route:
            route = Route(origin=origin, destination=dest)
            self.db.add(route)
            self.db.commit()
        return route

    def _subscribe_route(self, user_id: str, origin: str, dest: str, target: float | None) -> str:
        route = self._get_or_create_route(origin, dest)
        existing = self.db.query(UserSubscription).filter_by(
            user_id=user_id, route_id=route.id).first()
        if existing:
            existing.target_price = target
        else:
            self.db.add(UserSubscription(user_id=user_id, route_id=route.id, target_price=target))
        self.db.commit()
        return tmpl.subscribed_reply(route.origin, route.destination, target)

    def _fare_query(self, origin: str, dest: str) -> str:
        route = self.db.query(Route).filter_by(
            origin=origin.upper(), destination=dest.upper()).first()
        if not route:
            return tmpl.no_route_reply(origin.upper(), dest.upper())
        cheapest = self.fare_service.get_cheapest_fare(route.id)
        if not cheapest:
            return tmpl.no_fare_data_reply(route.origin, route.destination)
        return tmpl.fare_found_reply(
            route.origin, route.destination, cheapest["price_local"],
            cheapest["currency_local"], cheapest["price_usd"], cheapest["source"])

    def _track_flight(self, user_id: str, flight_number: str, date_str: str | None) -> str:
        flight_number = flight_number.upper()
        date = None
        if date_str:
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return "Date format should be YYYY-MM-DD, e.g. TRACK P47123 2026-07-20"
        flight = self.db.query(Flight).filter_by(flight_number=flight_number).first()
        if not flight:
            flight = Flight(flight_number=flight_number, date=date)
            self.db.add(flight)
            self.db.commit()
        existing = self.db.query(UserSubscription).filter_by(
            user_id=user_id, flight_id=flight.id).first()
        if not existing:
            self.db.add(UserSubscription(user_id=user_id, flight_id=flight.id))
            self.db.commit()
        return tmpl.tracking_reply(flight_number)

    def _maybe_status_report(self, user_id: str, text: str) -> str:
        sub = (self.db.query(UserSubscription)
               .filter(UserSubscription.user_id == user_id,
                       UserSubscription.flight_id.isnot(None))
               .order_by(UserSubscription.created_at.desc())
               .first())
        if not sub:
            return HELP_TEXT

        status_type, gate = MessageParser.parse(text)
        if status_type == StatusType.OTHER and gate is None:
            return tmpl.unclear_report_reply()

        report = self.status_service.add_report(
            sub.flight_id, user_id, status_type, gate, text)
        if report is None:
            return tmpl.rate_limited_reply()
        flight = self.db.query(Flight).get(sub.flight_id)
        return tmpl.report_logged_reply(status_type.value, gate, flight.flight_number)
