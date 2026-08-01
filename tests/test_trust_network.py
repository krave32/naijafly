"""Tests for the Phase-1 moat features: ReporterScore trust system and
flight-number live channels.

Feature 1 (trust):
  - Reporters earn 'trusted' after TRUSTED_CONFIRMED_REPORTS confirmed reports
  - A single trusted report can confirm a status (double weight)
  - Flagged reporters never confirm, never trigger pushes

Feature 2 (live channel):
  - A confirmed status reaches ALL users tracking the same flight NUMBER,
    even if they created separate Flight rows
  - Each user in the channel gets exactly one message (dedup)
"""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Flight, StatusReport, StatusType, ReportStatus,
    UserSubscription, ReporterScore,
)
from app.services.status_service import (
    StatusAggregationService, TRUSTED_CONFIRMED_REPORTS,
)


def _fresh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, to, body):
        self.sent.append({"to": to, "body": body})
        return True


def _make_flight(db, number="P47123"):
    flight = Flight(flight_number=number)
    db.add(flight)
    db.commit()
    return flight


# ---------------------------------------------------------------------------
# Trust system
# ---------------------------------------------------------------------------

def test_reporters_become_trusted_after_confirmed_reports():
    db = _fresh_db()
    service = StatusAggregationService(db)
    flight = _make_flight(db)

    # user1 confirms the same boarding across several flights
    for i in range(TRUSTED_CONFIRMED_REPORTS):
        f = _make_flight(db, number=f"P47{i}00")
        service.add_report(f.id, "user1", StatusType.BOARDING, "12", "boarding now")
        # a second user confirms so it goes through
        service.add_report(f.id, "user2", StatusType.BOARDING, "12", "boarding")

    score = db.query(ReporterScore).filter_by(reporter_id="user1").first()
    assert (score.confirmed_reports or 0) >= TRUSTED_CONFIRMED_REPORTS
    assert score.trust_level == "trusted"
    assert service.is_trusted("user1")


def test_single_trusted_report_confirms_status():
    """A trusted reporter's word alone carries enough weight to confirm."""
    db = _fresh_db()
    service = StatusAggregationService(db)

    # userA gets promoted to trusted across earlier flights
    for i in range(TRUSTED_CONFIRMED_REPORTS):
        f = _make_flight(db, number=f"P5{i}00")
        service.add_report(f.id, "userA", StatusType.BOARDING, "1", "boarding")
        service.add_report(f.id, "userB", StatusType.BOARDING, "1", "boarding")

    assert service.is_trusted("userA")

    # On a fresh flight, ONLY userA reports -> should confirm (2x weight)
    flight = _make_flight(db, number="P5999")
    service.add_report(flight.id, "userA", StatusType.BOARDING, "3", "boarding at gate 3")

    report = db.query(StatusReport).filter_by(flight_id=flight.id).first()
    assert report.status == ReportStatus.CONFIRMED


def test_flagged_reporter_never_confirms():
    """A flagged reporter's report is stored but never confirms anything."""
    db = _fresh_db()
    service = StatusAggregationService(db)
    flight = _make_flight(db)

    # userX gives 3 contradicted reports -> flagged
    for i in range(3):
        f = _make_flight(db, number=f"P6{i}00")
        # report 1 then report 2 with opposite state -> userX lands on losing side
        service.add_report(f.id, "userX", StatusType.DELAY, None, "delay")
        service.add_report(f.id, "userY", StatusType.BOARDING, "2", "boarding")
        service.add_report(f.id, "userZ", StatusType.BOARDING, "2", "boarding")
        # userY+userZ confirm boarding, userX's delay is contradicted

    assert service.is_flagged("userX")

    # A fresh flight where ONLY flagged userX reports -> must stay PENDING
    fresh = _make_flight(db, number="P6888")
    service.add_report(fresh.id, "userX", StatusType.BOARDING, "9", "boarding gate 9")
    report = db.query(StatusReport).filter_by(flight_id=fresh.id).first()
    assert report.status == ReportStatus.PENDING


# ---------------------------------------------------------------------------
# Live channel
# ---------------------------------------------------------------------------

def test_confirmed_status_reaches_all_users_on_same_flight_number():
    """Two users tracked 'P47123' via separate Flight rows - both get the push."""
    db = _fresh_db()
    notifier = FakeNotifier()
    service = StatusAggregationService(db, notifier=notifier)

    # User A tracked the flight (Flight row #1)
    f1 = _make_flight(db, number="P47123")
    db.add(UserSubscription(user_id="whatsapp:userA", flight_id=f1.id))
    # User B tracked the SAME number later (separate Flight row #2)
    f2 = _make_flight(db, number="p47123")  # lowercase on purpose
    db.add(UserSubscription(user_id="whatsapp:userB", flight_id=f2.id))
    db.commit()

    # Two reports on f1 confirm boarding
    service.add_report(f1.id, "rep1", StatusType.BOARDING, "12", "boarding 12")
    service.add_report(f1.id, "rep2", StatusType.BOARDING, "12", "boarding 12")

    pushed_to = {m["to"] for m in notifier.sent}
    assert "whatsapp:userA" in pushed_to
    assert "whatsapp:userB" in pushed_to


def test_live_channel_dedupes_per_user():
    """If one user somehow subscribed twice, they still get one message."""
    db = _fresh_db()
    notifier = FakeNotifier()
    service = StatusAggregationService(db, notifier=notifier)

    f1 = _make_flight(db, number="P47123")
    db.add(UserSubscription(user_id="whatsapp:userA", flight_id=f1.id))
    db.add(UserSubscription(user_id="whatsapp:userA", flight_id=f1.id))
    db.commit()

    service.add_report(f1.id, "rep1", StatusType.GATE_CHANGE, "B3", "gate B3")
    service.add_report(f1.id, "rep2", StatusType.GATE_CHANGE, "B3", "gate B3")

    assert len(notifier.sent) == 1
    assert notifier.sent[0]["to"] == "whatsapp:userA"
