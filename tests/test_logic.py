import os
import sys

# Add the current directory (naijafly root) to sys.path
sys.path.append(os.path.abspath(os.getcwd()))

from app.utils.parser import MessageParser
from app.models.models import StatusType, ReportStatus, Base, Flight, StatusReport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.status_service import StatusAggregationService

def test_parser():
    parser = MessageParser()
    
    status, gate = parser.parse("Boarding now gate 12")
    assert status == StatusType.BOARDING
    assert gate == "12"
    
    status, gate = parser.parse("Gate changed to E5")
    assert status == StatusType.GATE_CHANGE
    assert gate == "E5"
    
    status, gate = parser.parse("2hr delay announced")
    assert status == StatusType.DELAY

def _fresh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_status_aggregation_confirms_at_threshold():
    db = _fresh_db()
    service = StatusAggregationService(db)

    flight = Flight(flight_number="P47123")
    db.add(flight)
    db.commit()

    # Report 1 -> PENDING (threshold is 2)
    service.add_report(flight.id, "user1", StatusType.BOARDING, "12", "Boarding now gate 12")
    r1 = db.query(StatusReport).first()
    assert r1.status == ReportStatus.PENDING

    # Report 2 (different user, same info) -> both CONFIRMED
    service.add_report(flight.id, "user2", StatusType.BOARDING, "12", "started boarding at 12")
    reports = db.query(StatusReport).all()
    assert all(r.status == ReportStatus.CONFIRMED for r in reports)


def test_status_aggregation_majority_wins_over_minority():
    """A single late/wrong report shouldn't flip an already-confirmed status.

    NOTE: this replaces an earlier version of this test that asserted ALL
    reports go to DISPUTED as soon as any conflicting report arrives. That
    assertion didn't match the actual (intentional, documented in
    status_service.py) majority-wins rule: when the leading bucket has
    >= confirmation_threshold reports AND >= 2x the rival bucket, the
    majority is confirmed/stays confirmed and only the minority is marked
    DISPUTED. The old test was failing against correct code - fixed here to
    test the behavior that's actually implemented.
    """
    db = _fresh_db()
    service = StatusAggregationService(db)

    flight = Flight(flight_number="P47123")
    db.add(flight)
    db.commit()

    service.add_report(flight.id, "user1", StatusType.BOARDING, "12", "Boarding now gate 12")
    service.add_report(flight.id, "user2", StatusType.BOARDING, "12", "started boarding at 12")
    # 2 BOARDING reports are now CONFIRMED. A single conflicting report arrives:
    service.add_report(flight.id, "user3", StatusType.DELAY, None, "Wait, delay announced")

    reports = db.query(StatusReport).all()
    boarding_reports = [r for r in reports if r.status_type == StatusType.BOARDING]
    delay_reports = [r for r in reports if r.status_type == StatusType.DELAY]

    assert all(r.status == ReportStatus.CONFIRMED for r in boarding_reports)
    assert all(r.status == ReportStatus.DISPUTED for r in delay_reports)


def test_status_aggregation_genuine_tie_stays_disputed():
    """A real 1-vs-1 tie (no majority yet) should NOT confirm either side."""
    db = _fresh_db()
    service = StatusAggregationService(db)

    flight = Flight(flight_number="P47999")
    db.add(flight)
    db.commit()

    service.add_report(flight.id, "user1", StatusType.BOARDING, "12", "Boarding now gate 12")
    service.add_report(flight.id, "user2", StatusType.DELAY, None, "delay announced")

    reports = db.query(StatusReport).all()
    assert all(r.status == ReportStatus.DISPUTED for r in reports)


if __name__ == "__main__":
    test_parser()
    test_status_aggregation_confirms_at_threshold()
    test_status_aggregation_majority_wins_over_minority()
    test_status_aggregation_genuine_tie_stays_disputed()
    print("Tests passed!")
