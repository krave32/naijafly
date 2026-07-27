"""Tests for three critical bugs found in live WhatsApp testing.

BUG 1: Unsolicited fare-drop alerts sent to users with no subscription.
  - Root cause: Stale test subscriptions in production DB, not a code bug.
  - Fix: Verified that onboarding (HI/HELLO) only creates SeenUser rows,
    never UserSubscription rows. Fare alerts correctly filter by route_id.

BUG 2: Near-duplicate alerts for same price 4 hours apart on same route.
  - Root cause: alerted_users_this_batch was scoped per-date, allowing same
    user to get alerted for different sampled dates in same worker cycle.
  - Fix: cross_date_alerted set persists across all dates in a cycle.

BUG 3: STOP command intercepted by Twilio at platform level.
  - Root cause: Twilio intercepts STOP/START/HELP/UNSUBSCRIBE before webhook.
  - Fix: Added /webhook/optout endpoint, removed STOP from STOP_COMMANDS,
    kept UNSUBSCRIBE/CANCEL/QUIT/REMOVE as fallback keywords.
"""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, UserSubscription, Route, Fare, AlertHistory, SeenUser,
)
from app.services.bot_router import BotRouter, STOP_COMMANDS
from app.services.fare_service import FareService
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


def _fare_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    notifier = FakeNotifier()
    return FareService(db, notifier=notifier), db, notifier


# ============================================================================
# BUG 1: Unsolicited fare-drop alerts to users with no subscription
# ============================================================================

class TestBug1_UnsolicitedAlerts:
    """Verify users who only said 'Hi' never receive fare-drop pushes."""

    def test_hi_only_creates_seen_user_not_subscription(self):
        """Saying 'Hi' creates SeenUser but NOT UserSubscription."""
        router, db, _ = _router()
        user = "whatsapp:bug1_user_1"

        # User sends only "Hi"
        reply = router.handle(user, "Hi")

        # Verify SeenUser created (for welcome tracking)
        seen = db.query(SeenUser).filter_by(user_id=user).first()
        assert seen is not None

        # Verify NO UserSubscription created
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0, "Hi should never create a subscription"

        # Verify welcome message returned
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_non_command_messages_never_create_subscription(self):
        """Random non-command messages never create subscriptions."""
        router, db, _ = _router()
        user = "whatsapp:bug1_user_2"

        # Send various non-command messages
        router.handle(user, "random gibberish")
        router.handle(user, "hello there")
        router.handle(user, "what's up")

        # Verify NO subscriptions created
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_fare_drop_not_sent_to_user_without_subscription(self):
        """User without subscription receives ZERO fare-drop alerts."""
        service, db, notifier = _fare_service()
        user = "whatsapp:bug1_user_3"

        # Create a route
        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()

        # User has SeenUser but NO subscription
        db.add(SeenUser(user_id=user))
        db.commit()

        # Create an old expensive fare
        old_fare = Fare(
            route_id=route.id, price=150000, currency="NGN",
            source="Air Peace", flight_date=datetime.utcnow() + timedelta(days=5),
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.add(old_fare)
        db.commit()

        # Process a new cheap fare (should trigger alert for subscribers)
        new_fares = [{
            "price": 80000,  # Much cheaper
            "currency": "NGN",
            "source": "Air Peace",
            "flight_date": datetime.utcnow() + timedelta(days=5),
        }]
        alerts = service.process_new_fares(route.id, new_fares)

        # Verify NO alerts sent (user has no subscription)
        assert alerts == 0
        assert len(notifier.sent) == 0

    def test_only_subscribed_users_receive_alerts(self):
        """Only users with explicit UserSubscription receive alerts."""
        service, db, notifier = _fare_service()
        user_subscribed = "whatsapp:bug1_subscribed"
        user_unsubscribed = "whatsapp:bug1_unsubscribed"

        # Create route
        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()

        # Only user_subscribed has a subscription
        db.add(UserSubscription(
            user_id=user_subscribed, route_id=route.id, target_price=100000
        ))
        db.add(SeenUser(user_id=user_subscribed))
        db.add(SeenUser(user_id=user_unsubscribed))
        db.commit()

        # Create old expensive fare
        old_fare = Fare(
            route_id=route.id, price=150000, currency="NGN",
            source="Air Peace", flight_date=datetime.utcnow() + timedelta(days=5),
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.add(old_fare)
        db.commit()

        # Process new cheap fare
        new_fares = [{
            "price": 80000,
            "currency": "NGN",
            "source": "Air Peace",
            "flight_date": datetime.utcnow() + timedelta(days=5),
        }]
        alerts = service.process_new_fares(route.id, new_fares)

        # Verify exactly ONE alert sent (to subscribed user only)
        assert alerts == 1
        assert len(notifier.sent) == 1
        assert notifier.sent[0]["to"] == user_subscribed

        # Verify unsubscribed user received nothing
        unsubscribed_alerts = db.query(AlertHistory).filter_by(
            user_id=user_unsubscribed).count()
        assert unsubscribed_alerts == 0


# ============================================================================
# BUG 2: Near-duplicate alerts across sampled dates in same cycle
# ============================================================================

class TestBug2_CrossDateDeduplication:
    """Verify cross-date dedup prevents duplicate alerts in same cycle."""

    def test_no_duplicate_alerts_across_dates_same_cycle(self):
        """Same user gets at most ONE alert per route per cycle, even across dates."""
        service, db, notifier = _fare_service()
        user = "whatsapp:bug2_user_1"

        # Create route
        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()

        # User has rolling-window subscription (no target_date)
        db.add(UserSubscription(user_id=user, route_id=route.id, target_price=110000))
        db.commit()

        # Simulate worker cycle: process multiple dates for same route
        cross_date_alerted = set()

        # Date 1: cheap fare triggers alert
        date1 = datetime.utcnow() + timedelta(days=5)
        fares_date1 = [{
            "price": 107262,  # Below target
            "currency": "NGN",
            "source": "Air Peace",
            "flight_date": date1,
        }]
        alerts1 = service.process_new_fares(
            route.id, fares_date1, cross_date_alerted=cross_date_alerted)

        # Verify alert sent for date 1
        assert alerts1 == 1
        assert len(notifier.sent) == 1

        # Date 2: similarly cheap fare (would normally trigger another alert)
        date2 = datetime.utcnow() + timedelta(days=10)
        fares_date2 = [{
            "price": 107259,  # Essentially same price, also below target
            "currency": "NGN",
            "source": "Air Peace",
            "flight_date": date2,
        }]
        alerts2 = service.process_new_fares(
            route.id, fares_date2, cross_date_alerted=cross_date_alerted)

        # Verify NO second alert (cross-date dedup working)
        assert alerts2 == 0
        assert len(notifier.sent) == 1, "Should still be only 1 alert total"

        # Verify cross_date_alerted set contains the user-route pair
        assert (user, route.id) in cross_date_alerted

    def test_different_routes_can_alert_same_cycle(self):
        """Different routes can each alert once per cycle."""
        service, db, notifier = _fare_service()
        user = "whatsapp:bug2_user_2"

        # Create two routes
        route1 = Route(origin="LOS", destination="ABV")
        route2 = Route(origin="LOS", destination="ENU")
        db.add_all([route1, route2])
        db.commit()

        # User subscribed to both routes
        db.add(UserSubscription(user_id=user, route_id=route1.id, target_price=110000))
        db.add(UserSubscription(user_id=user, route_id=route2.id, target_price=110000))
        db.commit()

        cross_date_alerted = set()

        # Route 1: cheap fare
        fares_r1 = [{
            "price": 100000, "currency": "NGN", "source": "Air Peace",
            "flight_date": datetime.utcnow() + timedelta(days=5),
        }]
        alerts_r1 = service.process_new_fares(
            route1.id, fares_r1, cross_date_alerted=cross_date_alerted)

        # Route 2: cheap fare
        fares_r2 = [{
            "price": 100000, "currency": "NGN", "source": "Air Peace",
            "flight_date": datetime.utcnow() + timedelta(days=5),
        }]
        alerts_r2 = service.process_new_fares(
            route2.id, fares_r2, cross_date_alerted=cross_date_alerted)

        # Verify BOTH routes alerted (different routes, same user is OK)
        assert alerts_r1 == 1
        assert alerts_r2 == 1
        assert len(notifier.sent) == 2

    def test_same_route_multiple_dates_only_one_alert(self):
        """Multiple dates for same route in one cycle = exactly one alert."""
        service, db, notifier = _fare_service()
        user = "whatsapp:bug2_user_3"

        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()

        db.add(UserSubscription(user_id=user, route_id=route.id, target_price=110000))
        db.commit()

        cross_date_alerted = set()

        # Process 3 different dates, all with cheap fares
        for day_offset in [5, 10, 15]:
            fares = [{
                "price": 100000, "currency": "NGN", "source": "Air Peace",
                "flight_date": datetime.utcnow() + timedelta(days=day_offset),
            }]
            service.process_new_fares(
                route.id, fares, cross_date_alerted=cross_date_alerted)

        # Verify exactly ONE alert total (not 3)
        assert len(notifier.sent) == 1


# ============================================================================
# BUG 3: STOP command intercepted by Twilio
# ============================================================================

class TestBug3_TwilioStopInterception:
    """Verify STOP is NOT in STOP_COMMANDS and opt-out webhook works."""

    def test_stop_not_in_stop_commands(self):
        """'STOP' must NOT be in STOP_COMMANDS (Twilio intercepts it)."""
        assert "STOP" not in STOP_COMMANDS

    def test_unsubscribe_is_in_stop_commands(self):
        """'UNSUBSCRIBE' must be in STOP_COMMANDS (webhook fallback)."""
        assert "UNSUBSCRIBE" in STOP_COMMANDS

    def test_stop_command_variants_present(self):
        """All expected unsubscribe variants are present."""
        expected = {"UNSUBSCRIBE", "CANCEL", "QUIT", "REMOVE"}
        assert expected == STOP_COMMANDS

    def test_unsubscribe_removes_subscriptions(self):
        """UNSUBSCRIBE command removes all subscriptions."""
        router, db, _ = _router()
        user = "whatsapp:bug3_user_1"

        # Create subscriptions
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        router.handle(user, "SUBSCRIBE LOS ENU 90000")

        subs_before = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_before == 2

        # Send UNSUBSCRIBE
        reply = router.handle(user, "UNSUBSCRIBE")

        subs_after = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_after == 0
        assert "unsubscribed" in reply.lower() or "2" in reply

    def test_cancel_removes_subscriptions(self):
        """CANCEL command removes all subscriptions."""
        router, db, _ = _router()
        user = "whatsapp:bug3_user_2"

        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        router.handle(user, "CANCEL")

        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_quit_removes_subscriptions(self):
        """QUIT command removes all subscriptions."""
        router, db, _ = _router()
        user = "whatsapp:bug3_user_3"

        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        router.handle(user, "QUIT")

        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_remove_removes_subscriptions(self):
        """REMOVE command removes all subscriptions."""
        router, db, _ = _router()
        user = "whatsapp:bug3_user_4"

        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        router.handle(user, "REMOVE")

        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_stop_keyword_does_not_trigger_unsubscribe(self):
        """Literal 'STOP' does NOT trigger unsubscribe (Twilio intercepts it)."""
        router, db, _ = _router()
        user = "whatsapp:bug3_user_5"

        # Create subscription
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        subs_before = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_before == 1

        # Send literal "STOP" - should NOT unsubscribe
        reply = router.handle(user, "STOP")

        # Subscription should still exist
        subs_after = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_after == 1, "STOP should not unsubscribe (Twilio intercepts it)"

        # Should get a fallback message (not recognized as command)
        assert "didn't quite catch" in reply.lower() or "help" in reply.lower()

    def test_opt_out_webhook_logic(self):
        """Simulate Twilio opt-out webhook calling delete_user_data."""
        from app.utils.data_deletion import delete_user_data
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()

        user = "whatsapp:bug3_user_6"

        # Create subscriptions
        route = Route(origin="LOS", destination="ABV")
        db.add(route)
        db.commit()

        db.add(UserSubscription(user_id=user, route_id=route.id, target_price=80000))
        db.add(SeenUser(user_id=user))
        db.commit()

        # Verify subscriptions exist
        subs_before = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_before == 1

        # Simulate opt-out webhook calling delete_user_data
        removed = delete_user_data(db, user)

        # Verify subscriptions removed
        subs_after = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_after == 0
        assert removed == 1

        # Verify SeenUser removed (allows fresh welcome if they return)
        seen = db.query(SeenUser).filter_by(user_id=user).first()
        assert seen is None


# ============================================================================
# Privacy/Onboarding Text Verification
# ============================================================================

class TestPrivacyTextAccuracy:
    """Verify onboarding/privacy text matches actual opt-out behavior."""

    def test_welcome_mentions_unsubscribe_not_stop(self):
        """Welcome intro mentions UNSUBSCRIBE (not STOP) for data removal."""
        intro = tmpl.welcome_intro()

        # Should mention UNSUBSCRIBE
        assert "UNSUBSCRIBE" in intro

        # Should NOT mention STOP as the primary opt-out method
        # (STOP is intercepted by Twilio and never reaches our webhook)
        # Note: "STOP" might appear in context like "stop alerts" but should
        # not be presented as the command to send
        lines = intro.split('\n')
        for line in lines:
            if "send" in line.lower() and "unsubscribe" in line.lower():
                # This is the opt-out instruction line
                assert "UNSUBSCRIBE" in line
                # Should not say "Send STOP"
                assert "Send STOP" not in line and "send STOP" not in line

    def test_help_text_mentions_unsubscribe(self):
        """HELP text mentions UNSUBSCRIBE command."""
        from app.services.bot_router import HELP_TEXT
        assert "UNSUBSCRIBE" in HELP_TEXT

    def test_stop_confirmation_message(self):
        """Stop confirmation message is appropriate."""
        msg_with_subs = tmpl.stop_confirmation(3)
        assert "unsubscribed" in msg_with_subs.lower()
        assert "3" in msg_with_subs

        msg_no_subs = tmpl.stop_confirmation(0)
        assert "no active" in msg_no_subs.lower()

    def test_welcome_privacy_notice_mentions_data_deletion(self):
        """Welcome intro mentions data deletion capability."""
        intro = tmpl.welcome_intro()
        assert "delete" in intro.lower() or "remove" in intro.lower()

    def test_welcome_mentions_what_data_is_stored(self):
        """Welcome intro mentions what data is stored."""
        intro = tmpl.welcome_intro()
        # Should mention phone number
        assert "phone" in intro.lower() or "number" in intro.lower()
        # Should mention routes or subscriptions
        assert "route" in intro.lower() or "subscrib" in intro.lower()
