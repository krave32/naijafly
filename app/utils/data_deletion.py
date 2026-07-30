"""Shared data deletion utility for NDPA compliance.

Used by both bot_router.py (for app-level STOP/UNSUBSCRIBE commands) and
main.py (for Twilio opt-out webhook). Centralized to avoid duplication
and ensure consistent behavior.
"""
from sqlalchemy.orm import Session


def delete_user_data(db: Session, user_id: str, anonymous_id: str = "[deleted]") -> int:
    """NDPA-compliant data deletion for a user.

    Deletes all subscriptions, anonymizes historical records, removes SeenUser.
    Returns the total number of subscriptions removed.

    This is called from:
    1. bot_router._handle_stop() — when user sends UNSUBSCRIBE/CANCEL/etc.
    2. main.opt_out_webhook() — when Twilio sends the opt-out callback for STOP
    """
    from app.models.models import (
        UserSubscription, AlertHistory, StatusReport, ReporterScore, SeenUser,
        AirlineRequest,
    )

    fare_subs = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.route_id.isnot(None)
    ).count()
    flight_subs = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.flight_id.isnot(None)
    ).count()

    # Delete all subscriptions
    db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id
    ).delete(synchronize_session=False)

    # Anonymize alert history
    db.query(AlertHistory).filter(
        AlertHistory.user_id == user_id
    ).update({"user_id": anonymous_id}, synchronize_session=False)

    # Anonymize status reports
    db.query(StatusReport).filter(
        StatusReport.reporter_id == user_id
    ).update({"reporter_id": anonymous_id}, synchronize_session=False)

    # Anonymize reporter score
    db.query(ReporterScore).filter(
        ReporterScore.reporter_id == user_id
    ).update({"reporter_id": anonymous_id}, synchronize_session=False)

    # Anonymize airline tracking suggestions
    db.query(AirlineRequest).filter(
        AirlineRequest.user_id == user_id
    ).update({"user_id": anonymous_id}, synchronize_session=False)

    # Remove SeenUser record (allows fresh welcome if they re-engage)
    db.query(SeenUser).filter(
        SeenUser.user_id == user_id
    ).delete(synchronize_session=False)

    db.commit()
    return fare_subs + flight_subs
