"""Inbound WhatsApp command router.

Commands (case-insensitive):
  SUBSCRIBE LOS ABV [80000]             -> fare-drop alerts, rolling 30-day window
  SUBSCRIBE LOS ABV 2026-08-15 [80000]  -> fare-drop alerts for specific date only
  FARE LOS ABV                           -> cheapest fare in next 30 days
  FARE LOS ABV 2026-08-15               -> cheapest fare for that specific date
  TRACK P47123 2026-07-20               -> live boarding/gate/delay pushes
  <free text while tracking>            -> treated as a status report
  HELP                                  -> command list

Returns the reply text to send back. All DB access goes through the session
passed in, so the router is fully unit-testable without HTTP or Twilio.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("naijafly.bot_router")

from app.models.models import Route, Flight, UserSubscription, StatusType
from app.services.fare_service import FareService
from app.services.status_service import StatusAggregationService
from app.utils.parser import MessageParser
from app.utils import notify_templates as tmpl

HELP_TEXT = (
    "NaijaFly commands:\n"
    "SUBSCRIBE <FROM> <TO> [target price] - fare drop alerts, next 30 days\n"
    "  e.g. SUBSCRIBE LOS ABV 80000\n"
    "SUBSCRIBE <FROM> <TO> <YYYY-MM-DD> [target price] - specific date only\n"
    "  e.g. SUBSCRIBE LOS ABV 2026-08-15 80000\n"
    "FARE <FROM> <TO> - cheapest fare in next 30 days\n"
    "FARE <FROM> <TO> <YYYY-MM-DD> - cheapest for that date\n"
    "TRACK <FLIGHT> <YYYY-MM-DD> - live boarding updates\n"
    "While tracking, text what you see: 'boarding now gate 12'\n"
    "HELP - this message"
)

# Rolling window for fare queries when no specific date given
FARE_WINDOW_DAYS = 30


def _try_parse_date(text: str) -> datetime | None:
    """Try to parse a YYYY-MM-DD date string. Returns None on failure."""
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _looks_like_date(text: str) -> bool:
    """Quick check if text looks like a YYYY-MM-DD date."""
    if len(text) != 10 or text[4] != '-' or text[7] != '-':
        return False
    try:
        int(text[:4])
        int(text[5:7])
        int(text[8:10])
        return True
    except ValueError:
        return False


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
            return self._handle_subscribe(user_id, parts[1:])
        if cmd == "FARE" and len(parts) >= 3:
            return self._handle_fare(parts[1:])
        if cmd == "TRACK" and len(parts) >= 2:
            date_str = parts[2] if len(parts) > 2 else None
            return self._track_flight(user_id, parts[1], date_str)

        # Not a command: if the user tracks any flight, treat as a status report
        return self._maybe_status_report(user_id, text)

    # ---- handlers ----

    def _handle_subscribe(self, user_id: str, args: list[str]) -> str:
        """Parse SUBSCRIBE args with optional date and target price.

        Formats:
          SUBSCRIBE LOS ABV                     -> rolling window, no target
          SUBSCRIBE LOS ABV 80000               -> rolling window, target=80000
          SUBSCRIBE LOS ABV 2026-08-15          -> specific date, no target
          SUBSCRIBE LOS ABV 2026-08-15 80000    -> specific date, target=80000
        """
        origin = args[0].upper()
        dest = args[1].upper()
        target_date = None
        target_price = None

        if len(args) > 2:
            third = args[2]
            if _looks_like_date(third):
                target_date = _try_parse_date(third)
                if target_date is None:
                    return f"Invalid date format: {third}. Use YYYY-MM-DD, e.g. 2026-08-15"
                if target_date.date() < datetime.utcnow().date():
                    return f"Date {third} is in the past. Use a future date."
                # Optional target price after date
                if len(args) > 3:
                    try:
                        target_price = float(args[3])
                    except ValueError:
                        return f"Invalid target price: {args[3]}. Use a number like 80000."
            else:
                # No date — treat as target price (rolling window)
                try:
                    target_price = float(third)
                except ValueError:
                    return f"Invalid argument: {third}. Expected a target price (e.g. 80000) or date (YYYY-MM-DD)."

        route = self._get_or_create_route(origin, dest)
        logger.info(
            "SUBSCRIBE: user=%s route=%s->%s (id=%s) date=%s target=%s",
            user_id, route.origin, route.destination, route.id,
            target_date.strftime("%Y-%m-%d") if target_date else "rolling",
            target_price)

        existing = self.db.query(UserSubscription).filter_by(
            user_id=user_id, route_id=route.id,
            target_date=target_date).first()
        if existing:
            existing.target_price = target_price
        else:
            self.db.add(UserSubscription(
                user_id=user_id, route_id=route.id,
                target_price=target_price, target_date=target_date))
        self.db.commit()

        date_label = (target_date.strftime("%Y-%m-%d")
                      if target_date else "next 30 days")
        return tmpl.subscribed_reply(
            route.origin, route.destination, target_price, date_label)

    def _handle_fare(self, args: list[str]) -> str:
        """Parse FARE args with optional date.

        Formats:
          FARE LOS ABV              -> cheapest in rolling window
          FARE LOS ABV 2026-08-15   -> cheapest for that specific date
        """
        origin = args[0].upper()
        dest = args[1].upper()
        target_date = None

        if len(args) > 2:
            third = args[2]
            if _looks_like_date(third):
                target_date = _try_parse_date(third)
                if target_date is None:
                    return f"Invalid date format: {third}. Use YYYY-MM-DD, e.g. 2026-08-15"
            else:
                return f"Invalid argument: {third}. Expected a date (YYYY-MM-DD) or nothing."

        route = self.db.query(Route).filter_by(
            origin=origin, destination=dest).first()
        if not route:
            return tmpl.no_route_reply(origin, dest)

        if target_date:
            cheapest = self.fare_service.get_cheapest_fare(
                route.id, specific_date=target_date)
        else:
            window_end = datetime.utcnow() + timedelta(days=FARE_WINDOW_DAYS)
            cheapest = self.fare_service.get_cheapest_fare(
                route.id, date_from=datetime.utcnow(), date_to=window_end)

        if not cheapest:
            return tmpl.no_fare_data_reply(route.origin, route.destination)

        date_label = (target_date.strftime("%Y-%m-%d")
                      if target_date else "next 30 days")
        return tmpl.fare_found_reply(
            route.origin, route.destination, cheapest["price_local"],
            cheapest["currency_local"], cheapest["price_usd"],
            cheapest["source"], date_label)

    def _get_or_create_route(self, origin: str, dest: str) -> Route:
        """Get existing route or create a new one. Handles race conditions."""
        origin, dest = origin.upper(), dest.upper()
        route = self.db.query(Route).filter_by(
            origin=origin, destination=dest).first()
        if not route:
            route = Route(origin=origin, destination=dest)
            self.db.add(route)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                route = self.db.query(Route).filter_by(
                    origin=origin, destination=dest).first()
        logger.info("Resolved route %s->%s (id=%s)", origin, dest, route.id)
        return route

    def _track_flight(self, user_id: str, flight_number: str, date_str: str | None) -> str:
        flight_number = flight_number.upper()
        date = None
        if date_str:
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return "Date format should be YYYY-MM-DD, e.g. TRACK P47123 2026-07-20"
        flight = self.db.query(Flight).filter_by(
            flight_number=flight_number).first()
        if not flight:
            flight = Flight(flight_number=flight_number, date=date)
            self.db.add(flight)
            self.db.commit()
        existing = self.db.query(UserSubscription).filter_by(
            user_id=user_id, flight_id=flight.id).first()
        if not existing:
            self.db.add(UserSubscription(
                user_id=user_id, flight_id=flight.id))
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
        return tmpl.report_logged_reply(
            status_type.value, gate, flight.flight_number)
