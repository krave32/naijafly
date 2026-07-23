"""Tests for date-aware fare logic + Nigeria-domestic scope.

Covers:
  - get_cheapest_fare() date scoping (the original bug fix)
  - Rolling-window vs specific-date subscriptions
  - Command parsing with optional date argument
  - Sampling logic respects FARE_WINDOW_SAMPLE_DAYS
  - Dana Air removed from active mock carriers
  - All fixtures use Nigeria-domestic routes only
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

sys.path.append(os.path.abspath(os.getcwd()))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Route, Fare, UserSubscription, AlertHistory,
)
from app.services.fare_service import FareService
from app.services.fare_ingestor import MockFareIngestor, WEST_AFRICAN_AIRLINES
from app.services.bot_router import BotRouter
from app.workers.fare_worker import _get_sample_dates, _collect_dates_to_fetch
from app.utils import notify_templates as tmpl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, to, body):
        self.sent.append({"to": to, "body": body})
        return True


def _fresh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _router():
    db = _fresh_db()
    notifier = FakeNotifier()
    return BotRouter(db, notifier=notifier), db, notifier


def _seed_route(db, origin, dest):
    route = Route(origin=origin, destination=dest)
    db.add(route)
    db.commit()
    return route


def _seed_fare(db, route_id, price, date, source="Air Peace"):
    fare = Fare(
        route_id=route_id, price=price, currency="NGN",
        source=source, flight_date=date)
    db.add(fare)
    db.commit()
    return fare


# ===========================================================================
# PART A: Dana Air removal + Nigeria-domestic scope
# ===========================================================================

class TestDanaAirRemoved:
    """Dana Air (9J) must not appear in active mock fare results."""

    def test_dana_air_not_in_mock_sources(self):
        """MockFareIngestor.SOURCES must not include 'Dana Air'."""
        ingestor = MockFareIngestor()
        assert "Dana Air" not in ingestor.SOURCES

    def test_dana_air_marked_defunct_in_airlines_map(self):
        """WEST_AFRICAN_AIRLINES entry for 9J must say 'defunct'."""
        assert "9J" in WEST_AFRICAN_AIRLINES
        assert "defunct" in WEST_AFRICAN_AIRLINES["9J"].lower()

    def test_mock_fares_never_attribute_to_dana_air(self):
        """Run mock ingestor many times; Dana Air should never be a source."""
        ingestor = MockFareIngestor(seed=42)
        for _ in range(100):
            fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))
            for fare in fares:
                assert "Dana Air" not in fare["source"]

    def test_mock_sources_only_nigerian_carriers(self):
        """All mock sources should be active Nigerian domestic carriers."""
        ingestor = MockFareIngestor()
        expected = {
            "Air Peace", "Arik Air", "Ibom Air",
            "United Nigeria Airlines", "ValueJet", "Green Africa Airways",
            "Overland Airways", "NG Eagle", "Max Air",
        }
        assert set(ingestor.SOURCES) == expected


class TestNigeriaDomesticRoutes:
    """Mock ingestor BASE_PRICES should only contain Nigeria-domestic routes."""

    def test_base_prices_no_cross_border(self):
        cross_border_airports = {"ACC", "KMS", "TML", "DKR", "ABJ", "FNA", "OUA"}
        for origin, dest in MockFareIngestor.BASE_PRICES:
            assert origin not in cross_border_airports, \
                f"Cross-border origin {origin} found in BASE_PRICES"
            assert dest not in cross_border_airports, \
                f"Cross-border dest {dest} found in BASE_PRICES"

    def test_base_prices_all_ngn(self):
        for (origin, dest), (_, currency) in MockFareIngestor.BASE_PRICES.items():
            assert currency == "NGN", \
                f"Non-NGN currency for {origin}->{dest}: {currency}"


# ===========================================================================
# PART B: Date-aware fare queries (the original bug fix)
# ===========================================================================

class TestGetCheapestFareDateScoping:
    """get_cheapest_fare() must not mix fares across unrelated dates."""

    def test_specific_date_returns_only_that_date(self):
        """The bug: cheap March fare returned for a Christmas query.

        Seed two fares for very different dates, confirm a specific-date
        query doesn't wrongly return the cheaper but irrelevant one.
        """
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")

        # Cheap fare in March
        _seed_fare(db, route.id, 45000, datetime(2026, 3, 15), "Air Peace")
        # Expensive fare on Christmas Eve
        _seed_fare(db, route.id, 150000, datetime(2026, 12, 24), "Air Peace")

        service = FareService(db)

        # Query for Christmas Eve — should get the expensive fare, NOT the
        # cheap March one
        result = service.get_cheapest_fare(
            route.id, specific_date=datetime(2026, 12, 24))
        assert result is not None
        assert result["price_local"] == 150000

    def test_specific_date_returns_cheapest_on_that_date(self):
        """Multiple fares on the same date — cheapest wins."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "PHC")

        _seed_fare(db, route.id, 85000, datetime(2026, 8, 15), "Air Peace")
        _seed_fare(db, route.id, 72000, datetime(2026, 8, 15), "Arik Air")
        _seed_fare(db, route.id, 95000, datetime(2026, 8, 15), "Ibom Air")

        service = FareService(db)
        result = service.get_cheapest_fare(
            route.id, specific_date=datetime(2026, 8, 15))
        assert result is not None
        assert result["price_local"] == 72000
        assert result["source"] == "Arik Air"

    def test_rolling_window_returns_cheapest_across_sampled_dates(self):
        """Window query returns the true minimum across all dates in range."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")

        # Fares on different dates within a 30-day window
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        _seed_fare(db, route.id, 90000, base + timedelta(days=5), "Air Peace")
        _seed_fare(db, route.id, 65000, base + timedelta(days=10), "Arik Air")
        _seed_fare(db, route.id, 80000, base + timedelta(days=20), "Ibom Air")
        # Fare outside the window
        _seed_fare(db, route.id, 50000, base + timedelta(days=60), "Air Peace")

        service = FareService(db)
        result = service.get_cheapest_fare(
            route.id,
            date_from=base,
            date_to=base + timedelta(days=30))
        assert result is not None
        # Should be 65000 (Arik Air on day+10), NOT 50000 (outside window)
        assert result["price_local"] == 65000
        assert result["source"] == "Arik Air"

    def test_no_date_returns_global_cheapest(self):
        """Legacy behavior: no date filter returns cheapest across all dates."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")

        _seed_fare(db, route.id, 90000, datetime(2026, 3, 1), "Air Peace")
        _seed_fare(db, route.id, 55000, datetime(2026, 12, 24), "Arik Air")

        service = FareService(db)
        result = service.get_cheapest_fare(route.id)
        assert result is not None
        assert result["price_local"] == 55000

    def test_specific_date_no_data_returns_none(self):
        """Query for a date with no fares returns None."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")
        _seed_fare(db, route.id, 85000, datetime(2026, 8, 1), "Air Peace")

        service = FareService(db)
        result = service.get_cheapest_fare(
            route.id, specific_date=datetime(2026, 9, 15))
        assert result is None


# ===========================================================================
# PART B: Date-aware process_new_fares
# ===========================================================================

class TestProcessNewFaresDateAware:
    """process_new_fares scopes prev_min/prev_avg to same date."""

    def test_date_scoped_comparison(self):
        """Fares for date A shouldn't trigger alerts against date B's history."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")
        notifier = FakeNotifier()
        service = FareService(db, notifier=notifier)

        # Seed expensive fare for Dec 24
        _seed_fare(db, route.id, 200000, datetime(2026, 12, 24), "Air Peace")

        # Add subscription (rolling window, no target)
        db.add(UserSubscription(
            user_id="user1", route_id=route.id))
        db.commit()

        # Process cheap fare for March 15 — should NOT trigger alert because
        # it's a different date than Dec 24, so prev_min for March 15 is None
        # (infinity), and running_min starts at infinity.
        fares = [{
            "price": 50000, "currency": "NGN", "source": "Air Peace",
            "flight_date": datetime(2026, 3, 15),
        }]
        alerts = service.process_new_fares(route.id, fares)
        # No alert because prev_avg is None (no prior March 15 fares)
        assert alerts == 0

    def test_same_date_alert_fires(self):
        """A genuinely cheaper fare on the same date triggers an alert."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")
        notifier = FakeNotifier()
        service = FareService(db, notifier=notifier)

        # Seed prior fares for Aug 15 — establish a baseline
        _seed_fare(db, route.id, 100000, datetime(2026, 8, 15), "Air Peace")
        _seed_fare(db, route.id, 95000, datetime(2026, 8, 15), "Arik Air")

        # Subscription
        db.add(UserSubscription(
            user_id="user1", route_id=route.id))
        db.commit()

        # New batch for Aug 15 — cheaper than both prior fares AND below avg
        fares = [{
            "price": 60000, "currency": "NGN", "source": "Ibom Air",
            "flight_date": datetime(2026, 8, 15),
        }]
        alerts = service.process_new_fares(route.id, fares)
        assert alerts == 1
        assert len(notifier.sent) == 1

    def test_target_date_subscription_ignores_other_dates(self):
        """A specific-date sub only gets alerted for fares on that date."""
        db = _fresh_db()
        route = _seed_route(db, "LOS", "ABV")
        notifier = FakeNotifier()
        service = FareService(db, notifier=notifier)

        # Subscription for Aug 15 only
        db.add(UserSubscription(
            user_id="user1", route_id=route.id,
            target_date=datetime(2026, 8, 15), target_price=80000))
        db.commit()

        # Cheap fare for Dec 24 — should NOT alert (wrong date)
        fares = [{
            "price": 50000, "currency": "NGN", "source": "Air Peace",
            "flight_date": datetime(2026, 12, 24),
        }]
        alerts = service.process_new_fares(route.id, fares)
        assert alerts == 0

        # Cheap fare for Aug 15 — SHOULD alert (correct date, below target)
        fares = [{
            "price": 70000, "currency": "NGN", "source": "Arik Air",
            "flight_date": datetime(2026, 8, 15),
        }]
        alerts = service.process_new_fares(route.id, fares)
        assert alerts == 1


# ===========================================================================
# PART B: Command parsing with dates
# ===========================================================================

class TestCommandParsingWithDates:
    """SUBSCRIBE and FARE accept optional date arguments."""

    def test_subscribe_rolling_window_no_date(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "next 30 days" in reply

    def test_subscribe_with_target_price_no_date(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 80000")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "80,000" in reply

    def test_subscribe_with_specific_date(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 2026-08-15")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "2026-08-15" in reply

    def test_subscribe_with_date_and_target(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 2026-08-15 80000")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "2026-08-15" in reply
        assert "80,000" in reply

    def test_subscribe_invalid_date_format(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 15-08-2026")
        assert "Invalid" in reply or "invalid" in reply.lower()

    def test_subscribe_past_date_rejected(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 2020-01-01")
        assert "past" in reply.lower()

    def test_subscribe_invalid_price_rejected(self):
        router, db, _ = _router()
        reply = router.handle("user1", "SUBSCRIBE LOS ABV notanumber")
        assert "Invalid" in reply or "invalid" in reply.lower()

    def test_fare_rolling_window_no_date(self):
        router, db, _ = _router()
        _seed_route(db, "LOS", "ABV")
        # Seed a fare within the rolling window
        base = datetime.utcnow()
        _seed_fare(db, 1, 75000, base + timedelta(days=5), "Air Peace")
        reply = router.handle("user1", "FARE LOS ABV")
        assert reply.startswith(tmpl.EMOJI_FARE_FOUND)
        assert "next 30 days" in reply

    def test_fare_specific_date(self):
        router, db, _ = _router()
        _seed_route(db, "LOS", "ABV")
        _seed_fare(db, 1, 85000, datetime(2026, 8, 15), "Arik Air")
        reply = router.handle("user1", "FARE LOS ABV 2026-08-15")
        assert reply.startswith(tmpl.EMOJI_FARE_FOUND)
        assert "2026-08-15" in reply

    def test_fare_invalid_arg_rejected(self):
        router, db, _ = _router()
        _seed_route(db, "LOS", "ABV")
        reply = router.handle("user1", "FARE LOS ABV hello")
        assert "Invalid" in reply or "invalid" in reply.lower()


# ===========================================================================
# PART B: Sampling logic
# ===========================================================================

class TestSamplingLogic:
    """_get_sample_dates respects FARE_WINDOW_SAMPLE_DAYS."""

    def test_sample_dates_count(self):
        """With window=30 and step=5, expect ~6 sample dates."""
        dates = _get_sample_dates(30, 5)
        assert 5 <= len(dates) <= 7

    def test_sample_dates_step(self):
        """Consecutive dates should be exactly step_days apart."""
        dates = _get_sample_dates(30, 5)
        for i in range(1, len(dates)):
            delta = (dates[i] - dates[i-1]).days
            assert delta == 5

    def test_sample_dates_within_window(self):
        """All dates should be within the window from tomorrow."""
        dates = _get_sample_dates(30, 5)
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        for d in dates:
            assert d > base  # after today
            assert d <= base + timedelta(days=30)  # within window

    def test_sample_dates_step_3(self):
        """With step=3, expect ~10 sample dates in 30-day window."""
        dates = _get_sample_dates(30, 3)
        assert 9 <= len(dates) <= 11

    def test_collect_dates_specific_subscription(self):
        """Specific-date sub only gets that one date."""
        target = datetime(2026, 9, 1)
        sub = MagicMock()
        sub.route_id = 1
        sub.target_date = target

        result = _collect_dates_to_fetch([sub], 30, 5)
        assert result[1] == {target}

    def test_collect_dates_rolling_subscription(self):
        """Rolling-window sub gets all sampled dates."""
        sub = MagicMock()
        sub.route_id = 1
        sub.target_date = None

        result = _collect_dates_to_fetch([sub], 30, 5)
        assert len(result[1]) == len(_get_sample_dates(30, 5))

    def test_collect_dates_deduplication(self):
        """Two subs on same route+date → fetched once."""
        target = datetime(2026, 9, 1)
        sub1 = MagicMock()
        sub1.route_id = 1
        sub1.target_date = target
        sub2 = MagicMock()
        sub2.route_id = 1
        sub2.target_date = target

        result = _collect_dates_to_fetch([sub1, sub2], 30, 5)
        # Same route, same date — set ensures dedup
        assert target in result[1]
        assert len(result[1]) == 1

    def test_collect_dates_skips_flight_only_subs(self):
        """Subscriptions with route_id=None (flight tracking) are skipped."""
        sub = MagicMock()
        sub.route_id = None
        sub.target_date = None

        result = _collect_dates_to_fetch([sub], 30, 5)
        assert len(result) == 0


# ===========================================================================
# PART B: Template date labels
# ===========================================================================

class TestTemplateDateLabels:
    """Templates correctly include date context."""

    def test_subscribed_reply_shows_date_label(self):
        msg = tmpl.subscribed_reply("LOS", "ABV", 80000, "2026-08-15")
        assert "2026-08-15" in msg
        assert "LOS->ABV" in msg

    def test_subscribed_reply_default_rolling(self):
        msg = tmpl.subscribed_reply("LOS", "ABV", None)
        assert "next 30 days" in msg

    def test_fare_found_reply_shows_date_label(self):
        msg = tmpl.fare_found_reply(
            "LOS", "ABV", 75000, "NGN", 50.0, "Air Peace", "2026-08-15")
        assert "2026-08-15" in msg
        assert "Air Peace" in msg

    def test_fare_drop_push_includes_date(self):
        msg = tmpl.fare_drop_push(
            "LOS", "ABV", 70000, "NGN", 46.67, "Arik Air", "2026-08-15")
        assert "2026-08-15" in msg

    def test_fare_drop_push_no_date(self):
        """When no date_label given, no parentheses appear."""
        msg = tmpl.fare_drop_push(
            "LOS", "ABV", 70000, "NGN", 46.67, "Arik Air")
        assert "()" not in msg
