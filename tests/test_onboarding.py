"""First-contact onboarding tests.

Validates:
  1. New user's first unrecognized message -> welcome intro (not generic unclear)
  2. New user's first valid command -> executes normally, no intro
  3. Returning user's unrecognized message -> normal unclear reply, NOT intro
  4. HI/HELLO/START/MENU -> always intro, new or returning
  5. First-contact tracking persists across handle() calls
"""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, SeenUser
from app.services.bot_router import BotRouter
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
    return BotRouter(db, notifier=notifier), db


class TestFirstContactIntro:
    """New user's first unrecognized message gets the welcome intro."""

    def test_new_user_random_text_gets_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:new_user_1", "what is this?")
        assert reply.startswith(tmpl.EMOJI_WELCOME)
        assert "Welcome to Araha" in reply

    def test_new_user_gibberish_gets_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:new_user_2", "asdkfjasldkfj")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_intro_mentions_fare_alerts_and_boarding(self):
        router, _ = _router()
        reply = router.handle("whatsapp:new_user_3", "hello there")
        # Should explain both features
        assert "fare" in reply.lower() or "Fare" in reply
        assert "boarding" in reply.lower() or "Boarding" in reply

    def test_intro_shows_example_commands(self):
        router, _ = _router()
        reply = router.handle("whatsapp:new_user_4", "hi there")
        assert "SUBSCRIBE" in reply
        assert "LOS" in reply  # realistic Nigerian route

    def test_intro_mentions_help(self):
        router, _ = _router()
        reply = router.handle("whatsapp:new_user_5", "random text")
        assert "HELP" in reply


class TestNewUserValidCommand:
    """New user's first message is a valid command -> executes normally."""

    def test_subscribe_no_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:cmd_user_1", "SUBSCRIBE LOS ABV 80000")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "Welcome" not in reply

    def test_fare_query_no_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:cmd_user_2", "FARE LOS ABV")
        # Either EMOJI_FARE_FOUND or EMOJI_NO_DATA, but NOT welcome intro
        assert not reply.startswith(tmpl.EMOJI_WELCOME)

    def test_track_no_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:cmd_user_3", "TRACK P47123 2026-08-01")
        assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)
        assert "Welcome" not in reply

    def test_help_no_intro(self):
        router, _ = _router()
        reply = router.handle("whatsapp:cmd_user_4", "HELP")
        assert "Flight Fare Tracker" in reply
        assert "Welcome" not in reply


class TestReturningUserNoIntro:
    """Returning user's unrecognized message -> normal unclear reply."""

    def test_second_unclear_message_gets_normal_reply(self):
        router, _ = _router()
        user = "whatsapp:returning_1"
        # First message: triggers intro and marks user as seen
        first = router.handle(user, "random text")
        assert first.startswith(tmpl.EMOJI_WELCOME)

        # Second message: normal unclear reply, NOT intro
        second = router.handle(user, "more random gibberish")
        assert not second.startswith(tmpl.EMOJI_WELCOME)
        assert "didn't quite catch that" in second

    def test_user_with_subscription_gets_normal_reply(self):
        router, _ = _router()
        user = "whatsapp:returning_2"
        # Create a subscription (marks user as seen)
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        # Now send gibberish -> should get unclear, not intro
        reply = router.handle(user, "asdkfjasldkfj gibberish")
        assert not reply.startswith(tmpl.EMOJI_WELCOME)


class TestGreetingKeywords:
    """HI/HELLO/START/MENU always trigger intro, new or returning."""

    def test_hi_new_user(self):
        router, _ = _router()
        reply = router.handle("whatsapp:hi_new", "HI")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_hello_new_user(self):
        router, _ = _router()
        reply = router.handle("whatsapp:hello_new", "Hello")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_start_new_user(self):
        router, _ = _router()
        reply = router.handle("whatsapp:start_new", "START")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_menu_new_user(self):
        router, _ = _router()
        reply = router.handle("whatsapp:menu_new", "menu")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_hi_returning_user(self):
        router, _ = _router()
        user = "whatsapp:hi_returning"
        # First interaction: subscribe (marks as seen)
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        # Now send HI -> still gets intro (on-demand)
        reply = router.handle(user, "HI")
        assert reply.startswith(tmpl.EMOJI_WELCOME)

    def test_hello_case_insensitive(self):
        router, _ = _router()
        for greeting in ["hi", "Hi", "HI", "hello", "HELLO", "Hello",
                         "start", "START", "menu", "MENU"]:
            user = f"whatsapp:case_{greeting}"
            reply = router.handle(user, greeting)
            assert reply.startswith(tmpl.EMOJI_WELCOME), \
                f"'{greeting}' should trigger welcome intro"


class TestFirstContactPersistence:
    """First-contact tracking persists across handle() calls."""

    def test_seen_user_persisted_in_db(self):
        router, db = _router()
        user = "whatsapp:persist_1"
        router.handle(user, "some random text")

        # Verify the SeenUser row exists
        seen = db.query(SeenUser).filter_by(user_id=user).first()
        assert seen is not None

    def test_second_session_same_number_not_first_contact(self):
        """Simulate a new request/session for the same number."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        # First session
        db1 = sessionmaker(bind=engine)()
        router1 = BotRouter(db1, notifier=FakeNotifier())
        reply1 = router1.handle("whatsapp:persist_2", "random text")
        assert reply1.startswith(tmpl.EMOJI_WELCOME)
        db1.close()

        # Second session (new DB session, same engine/data)
        db2 = sessionmaker(bind=engine)()
        router2 = BotRouter(db2, notifier=FakeNotifier())
        reply2 = router2.handle("whatsapp:persist_2", "more random text")
        # Should NOT be welcome intro - user was already seen
        assert not reply2.startswith(tmpl.EMOJI_WELCOME)
        db2.close()

    def test_no_duplicate_seen_user_on_second_message(self):
        router, db = _router()
        user = "whatsapp:no_dup"
        router.handle(user, "first message")
        router.handle(user, "second message")

        # Should be exactly one SeenUser row
        count = db.query(SeenUser).filter_by(user_id=user).count()
        assert count == 1

    def test_subscribe_first_then_gibberish_no_intro(self):
        """Valid command first, then gibberish -> no intro on second."""
        router, _ = _router()
        user = "whatsapp:sub_then_gibberish"
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        reply = router.handle(user, "random gibberish text")
        assert not reply.startswith(tmpl.EMOJI_WELCOME)
