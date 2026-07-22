"""Integration tests: real BotRouter.handle() calls, in-memory DB, no
network. Confirms the emoji templates are actually wired into the live
command flow, not just correct in isolation."""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base
from app.services.bot_router import BotRouter
from app.utils import notify_templates as tmpl


class FakeNotifier:
    """Records sends instead of hitting Twilio - lets us assert pushes fired."""

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
    return BotRouter(db, notifier=notifier), notifier


def test_subscribe_reply_has_emoji():
    router, _ = _router()
    reply = router.handle("+2348000000001", "SUBSCRIBE LOS ACC 80000")
    assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)


def test_fare_query_no_data_has_emoji():
    router, _ = _router()
    router.handle("+2348000000001", "SUBSCRIBE LOS ACC")
    reply = router.handle("+2348000000001", "FARE LOS ACC")
    # No fares ingested in this test (worker never ran), so this hits the
    # "no fare data yet" branch.
    assert reply.startswith(tmpl.EMOJI_NO_DATA)


def test_track_reply_has_emoji():
    router, _ = _router()
    reply = router.handle("+2348000000001", "TRACK P47123 2026-08-01")
    assert reply.startswith(tmpl.EMOJI_SUBSCRIBED)


def test_boarding_confirmation_push_reaches_two_subscribers():
    """Full loop: two distinct reporters -> confirmed -> both get a pushed,
    emoji-tagged WhatsApp message via the notifier."""
    router, notifier = _router()
    router.handle("+2348000000001", "TRACK P47123 2026-08-01")
    router.handle("+2348000000002", "TRACK P47123 2026-08-01")

    reply1 = router.handle("+2348000000001", "boarding now gate 12")
    assert reply1.startswith(tmpl.EMOJI_REPORT_LOGGED)
    assert len(notifier.sent) == 0  # still pending, nothing pushed yet

    reply2 = router.handle("+2348000000002", "boarding now gate 12")
    assert reply2.startswith(tmpl.EMOJI_REPORT_LOGGED)

    # Second matching report should have triggered a confirmed push to both.
    assert len(notifier.sent) == 2
    for msg in notifier.sent:
        assert msg["body"].startswith(tmpl.STATUS_PUSH_EMOJI[
            __import__("app.models.models", fromlist=["StatusType"]).StatusType.BOARDING])
        assert "P47123" in msg["body"]


def test_unclear_report_has_emoji():
    router, _ = _router()
    router.handle("+2348000000001", "TRACK P47123 2026-08-01")
    reply = router.handle("+2348000000001", "asdkfjasldkfj gibberish")
    assert reply.startswith(tmpl.EMOJI_UNCLEAR)
