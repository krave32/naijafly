"""Tests for the airline suggestion feature + Google Flights verification links.

Feature 1: Users can suggest airlines to track beyond the default set
  - "AIRLINE Xejet" command and natural phrases ("add airline Xejet")
  - Suggestions stored as AirlineRequest rows for ops review
  - Already-tracked airlines get a friendly "already covered" reply
  - AIRLINES lists the currently tracked (non-defunct) carriers
  - Approved suggestions flow in via EXTRA_TRACKED_AIRLINES (see
    test_google_flights_ingestor.py for the ingestor-side tests)

Feature 2: Fare replies and fare-drop pushes carry a direct Google Flights
search link so users can independently verify every price we show.
"""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, AirlineRequest, Route, Fare, UserSubscription
from app.services.bot_router import BotRouter, HELP_TEXT
from app.services.fare_service import FareService
from app.services.fare_ingestor import google_flights_url
from app.utils.intent_parser import parse_intent
from app.utils import notify_templates as tmpl


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, to, body):
        self.sent.append({"to": to, "body": body})
        return True


def _router():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    notifier = FakeNotifier()
    return BotRouter(db, notifier=notifier), db, notifier


# ============================================================================
# Intent parsing for airline suggestions
# ============================================================================

class TestAirlineIntentParsing:
    def test_add_airline_phrase(self):
        intent = parse_intent("add airline Xejet")
        assert intent.action == "airline_request"
        assert intent.airline == "Xejet"
        assert intent.confidence >= 0.4

    def test_track_airline_phrase_not_flight_track(self):
        """'track airline X' must NOT be mistaken for flight tracking."""
        intent = parse_intent("can you track airline Rano Air?")
        assert intent.action == "airline_request"
        assert intent.airline == "Rano Air"

    def test_name_before_keyword(self):
        intent = parse_intent("please add Xejet airways")
        assert intent.action == "airline_request"
        assert intent.airline == "Xejet"

    def test_airline_request_without_name(self):
        intent = parse_intent("suggest airline")
        assert intent.action == "airline_request"
        assert intent.airline is None
        assert intent.confidence == 0.5

    def test_which_airlines_is_list_intent(self):
        intent = parse_intent("which airlines do you track?")
        assert intent.action == "airline_list"
        assert intent.confidence >= 0.4

    def test_fare_query_still_wins_for_normal_messages(self):
        """Airline patterns must not swallow ordinary fare queries."""
        intent = parse_intent("cheap flights from Lagos to Abuja")
        assert intent.action == "fare_query"


# ============================================================================
# BotRouter: AIRLINE / AIRLINES commands and natural language
# ============================================================================

class TestAirlineSuggestionFlow:
    def test_airline_command_logs_request(self):
        router, db, _ = _router()
        user = "whatsapp:airline_user_1"
        reply = router.handle(user, "AIRLINE Xejet")
        assert reply.startswith(tmpl.EMOJI_AIRLINE)
        assert "Xejet" in reply

        row = db.query(AirlineRequest).filter_by(user_id=user).first()
        assert row is not None
        assert row.airline_name == "Xejet"
        assert row.status == "pending"

    def test_natural_language_logs_request(self):
        router, db, _ = _router()
        user = "whatsapp:airline_user_2"
        reply = router.handle(user, "can you add airline Rano Air for me")
        assert "Rano Air" in reply
        row = db.query(AirlineRequest).filter_by(user_id=user).first()
        assert row is not None
        assert row.airline_name == "Rano Air"

    def test_duplicate_request_not_stored_twice(self):
        router, db, _ = _router()
        user = "whatsapp:airline_user_3"
        router.handle(user, "AIRLINE Xejet")
        reply = router.handle(user, "AIRLINE Xejet")
        assert "already suggested" in reply.lower()
        count = db.query(AirlineRequest).filter_by(user_id=user).count()
        assert count == 1

    def test_already_tracked_airline_reply(self):
        """Suggesting Air Peace (already tracked) doesn't create a request."""
        router, db, _ = _router()
        user = "whatsapp:airline_user_4"
        reply = router.handle(user, "AIRLINE Air Peace")
        assert "already" in reply.lower()
        assert db.query(AirlineRequest).count() == 0

    def test_airline_command_without_name_prompts_then_resolves(self):
        """Bare AIRLINE asks which airline; the next reply is captured."""
        router, db, _ = _router()
        user = "whatsapp:airline_user_5"
        reply = router.handle(user, "AIRLINE")
        assert "which airline" in reply.lower()

        reply2 = router.handle(user, "Xejet")
        assert "Xejet" in reply2
        row = db.query(AirlineRequest).filter_by(user_id=user).first()
        assert row is not None and row.airline_name == "Xejet"

    def test_airlines_command_lists_tracked_carriers(self):
        router, _, _ = _router()
        reply = router.handle("whatsapp:airline_user_6", "AIRLINES")
        assert reply.startswith(tmpl.EMOJI_AIRLINE)
        assert "Air Peace" in reply
        assert "Arik Air" in reply
        # Defunct carriers are hidden from the user-facing list
        assert "Dana" not in reply

    def test_help_mentions_airline_commands(self):
        assert "AIRLINE" in HELP_TEXT
        assert "AIRLINES" in HELP_TEXT

    def test_unsubscribe_anonymizes_airline_requests(self):
        """NDPA: STOP flow anonymizes stored airline suggestions."""
        router, db, _ = _router()
        user = "whatsapp:airline_user_7"
        router.handle(user, "AIRLINE Xejet")
        router.handle(user, "UNSUBSCRIBE")
        assert db.query(AirlineRequest).filter_by(user_id=user).count() == 0
        anon = db.query(AirlineRequest).filter_by(user_id="[deleted]").count()
        assert anon == 1


# ============================================================================
# Google Flights verification links in user-facing messages
# ============================================================================

def _seed_route_with_fare(db, origin="LOS", dest="ABV", price=85000):
    route = Route(origin=origin, destination=dest)
    db.add(route)
    db.commit()
    db.add(Fare(
        route_id=route.id, price=price, currency="NGN",
        source="Air Peace (P4) via Google Flights",
        flight_date=datetime.utcnow() + timedelta(days=5),
    ))
    db.commit()
    return route


class TestVerificationLinks:
    def test_fare_command_reply_includes_google_flights_link(self):
        router, db, _ = _router()
        _seed_route_with_fare(db)
        reply = router.handle("whatsapp:link_user_1", "FARE LOS ABV")
        assert "google.com/travel/flights" in reply
        assert "Verify on Google Flights" in reply

    def test_natural_fare_reply_includes_link(self):
        router, db, _ = _router()
        _seed_route_with_fare(db)
        reply = router.handle("whatsapp:link_user_2", "cheap flights from Lagos to Abuja")
        assert "google.com/travel/flights" in reply

    def test_fare_reply_with_date_links_that_date(self):
        router, db, _ = _router()
        route = _seed_route_with_fare(db)
        # Add a fare on the specific date being queried
        db.add(Fare(
            route_id=route.id, price=90000, currency="NGN",
            source="Arik Air (W3) via Google Flights",
            flight_date=datetime(2026, 8, 15),
        ))
        db.commit()
        reply = router.handle("whatsapp:link_user_3", "FARE LOS ABV 2026-08-15")
        assert "2026-08-15" in reply
        assert "Flights+from+LOS+to+ABV+on+2026-08-15" in reply

    def test_fare_drop_push_includes_link(self):
        """Fare-drop alerts also carry the verification link."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        notifier = FakeNotifier()
        service = FareService(db, notifier=notifier)

        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()
        db.add(UserSubscription(
            user_id="whatsapp:link_user_4", route_id=route.id,
            target_price=100000))
        db.commit()

        service.process_new_fares(route.id, [{
            "price": 80000, "currency": "NGN",
            "source": "Air Peace (P4) via Google Flights",
            "flight_date": datetime.utcnow() + timedelta(days=5),
        }])

        assert len(notifier.sent) == 1
        assert "google.com/travel/flights" in notifier.sent[0]["body"]

    def test_no_fare_data_reply_has_no_link(self):
        """Empty results don't get a misleading 'verify' link."""
        router, db, _ = _router()
        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()
        reply = router.handle("whatsapp:link_user_5", "FARE LOS ABV")
        assert reply.startswith(tmpl.EMOJI_NO_DATA)
        assert "google.com" not in reply

    def test_template_without_link_unchanged(self):
        """Backward compat: templates called without link stay identical."""
        msg = tmpl.fare_found_reply("LOS", "ABV", 185000, "NGN", 123.45, "Air Peace")
        assert "google.com" not in msg
        push = tmpl.fare_drop_push("LOS", "ABV", 70000, "NGN", 46.67, "Air Peace")
        assert "google.com" not in push

    def test_google_flights_url_helper_matches_reply(self):
        link = google_flights_url("LOS", "ABV")
        router, db, _ = _router()
        _seed_route_with_fare(db)
        reply = router.handle("whatsapp:link_user_6", "FARE LOS ABV")
        assert link in reply
