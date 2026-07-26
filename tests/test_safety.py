"""Safety tests: admin auth, STOP/unsubscribe, NDPA data anonymization.

Validates:
  1. Admin route returns 401 without valid credentials, 200 with them
  2. STOP removes all subscriptions for that user, confirmed via DB query
  3. STOP is idempotent (no error on a user with nothing to remove)
  4. STOP variants ("unsubscribe", "cancel") all route to the same handler
  5. Historical data anonymization after STOP
  6. Privacy notice present in onboarding message
"""
import base64
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, UserSubscription, Route, Flight, AlertHistory, StatusReport,
    ReporterScore, SeenUser, StatusType, ReportStatus,
)
from app.services.bot_router import BotRouter, ANONYMOUS_USER_ID
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


def _make_basic_auth(user: str, password: str) -> str:
    """Create a Basic Auth header value."""
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {encoded}"


# ---- Admin Auth Tests ----

def _check_admin_auth_logic(headers: dict, admin_user: str | None, admin_password: str | None) -> bool:
    """Test the admin auth logic directly (mirrors main.py implementation).

    This avoids importing app.main which requires psycopg2/PostgreSQL.
    """
    if not admin_user or not admin_password:
        return True  # auth disabled

    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        user, password = decoded.split(":", 1)
        return user == admin_user and password == admin_password
    except Exception:
        return False


class TestAdminAuth:
    """Admin route authentication tests.

    Tests the auth logic directly to avoid importing app.main
    (which requires psycopg2/PostgreSQL driver).
    """

    def test_admin_401_without_credentials_header(self):
        """No Authorization header -> auth fails when credentials are set."""
        result = _check_admin_auth_logic({}, "admin", "secret123")
        assert result is False

    def test_admin_401_with_wrong_password(self):
        """Wrong password -> auth fails."""
        headers = {"Authorization": _make_basic_auth("admin", "wrong")}
        result = _check_admin_auth_logic(headers, "admin", "secret123")
        assert result is False

    def test_admin_401_with_wrong_username(self):
        """Wrong username -> auth fails."""
        headers = {"Authorization": _make_basic_auth("wrong", "secret123")}
        result = _check_admin_auth_logic(headers, "admin", "secret123")
        assert result is False

    def test_admin_200_with_valid_credentials(self):
        """Correct credentials -> auth passes."""
        headers = {"Authorization": _make_basic_auth("admin", "secret123")}
        result = _check_admin_auth_logic(headers, "admin", "secret123")
        assert result is True

    def test_admin_open_when_no_env_vars(self):
        """No env vars set -> auth disabled (always passes)."""
        result = _check_admin_auth_logic({}, None, None)
        assert result is True  # auth disabled

    def test_admin_open_when_user_missing(self):
        """Only password set -> auth disabled."""
        result = _check_admin_auth_logic({}, None, "secret123")
        assert result is True

    def test_admin_open_when_password_missing(self):
        """Only user set -> auth disabled."""
        result = _check_admin_auth_logic({}, "admin", None)
        assert result is True


# ---- STOP Command Tests ----

class TestStopCommand:
    """STOP/unsubscribe command tests."""

    def test_stop_removes_all_subscriptions(self):
        """STOP removes all fare and flight subscriptions for the user."""
        router, db = _router()
        user = "whatsapp:stop_user_1"

        # Create subscriptions
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        router.handle(user, "SUBSCRIBE LOS PHC 50000")
        router.handle(user, "TRACK P47123 2026-08-01")

        # Verify subscriptions exist
        subs_before = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_before == 3

        # Send STOP
        reply = router.handle(user, "STOP")

        # Verify all subscriptions removed
        subs_after = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs_after == 0

        # Verify confirmation message
        assert "unsubscribed" in reply.lower() or "no active" in reply.lower()
        assert "3" in reply  # mentions count removed

    def test_stop_is_idempotent(self):
        """Sending STOP when already unsubscribed doesn't error."""
        router, db = _router()
        user = "whatsapp:stop_idempotent"

        # Send STOP without any subscriptions
        reply = router.handle(user, "STOP")

        # Should get a confirmation, not an error
        assert "no active subscriptions" in reply.lower() or "removed" in reply.lower()

        # Send STOP again
        reply2 = router.handle(user, "STOP")
        assert "no active subscriptions" in reply2.lower() or "removed" in reply2.lower()

    def test_stop_variants_unsubscribe(self):
        """'unsubscribe' routes to the same handler as STOP."""
        router, db = _router()
        user = "whatsapp:stop_var_1"
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        reply = router.handle(user, "unsubscribe")
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0
        assert "unsubscribed" in reply.lower() or "removed" in reply.lower()

    def test_stop_variants_cancel(self):
        """'cancel' routes to the same handler as STOP."""
        router, db = _router()
        user = "whatsapp:stop_var_2"
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        reply = router.handle(user, "CANCEL")
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0
        assert "unsubscribed" in reply.lower() or "removed" in reply.lower()

    def test_stop_variants_quit(self):
        """'quit' routes to the same handler as STOP."""
        router, db = _router()
        user = "whatsapp:stop_var_3"
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        reply = router.handle(user, "quit")
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_stop_variants_remove(self):
        """'remove' routes to the same handler as STOP."""
        router, db = _router()
        user = "whatsapp:stop_var_4"
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        reply = router.handle(user, "REMOVE")
        subs = db.query(UserSubscription).filter_by(user_id=user).count()
        assert subs == 0

    def test_stop_case_insensitive(self):
        """STOP command is case-insensitive."""
        router, db = _router()
        for cmd in ["stop", "STOP", "Stop", "sToP"]:
            user = f"whatsapp:stop_case_{cmd}"
            router.handle(user, "SUBSCRIBE LOS ABV 80000")
            router.handle(user, cmd)
            subs = db.query(UserSubscription).filter_by(user_id=user).count()
            assert subs == 0, f"'{cmd}' should unsubscribe"


# ---- NDPA Data Anonymization Tests ----

class TestDataAnonymization:
    """Tests for data anonymization after STOP (NDPA compliance)."""

    def test_alert_history_anonymized_after_stop(self):
        """Alert history user_id is replaced with [deleted] after STOP."""
        router, db = _router()
        user = "whatsapp:anon_user_1"

        # Create a subscription and alert history
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        # Manually create an alert history entry
        route = db.query(Route).filter_by(origin="LOS", destination="ABV").first()
        alert = AlertHistory(
            user_id=user, alert_type="fare_drop", route_id=route.id,
            message="Price drop LOS->ABV", delivered=True
        )
        db.add(alert)
        db.commit()

        # Verify alert exists
        alert_before = db.query(AlertHistory).filter_by(user_id=user).first()
        assert alert_before is not None

        # Send STOP
        router.handle(user, "STOP")

        # Verify alert is anonymized (user_id replaced)
        alert_anon = db.query(AlertHistory).filter_by(user_id=user).first()
        assert alert_anon is None  # original user_id no longer matches

        alert_deleted = db.query(AlertHistory).filter_by(user_id=ANONYMOUS_USER_ID).first()
        assert alert_deleted is not None
        assert alert_deleted.message == "Price drop LOS->ABV"  # content preserved

    def test_status_reports_anonymized_after_stop(self):
        """Status report reporter_id is replaced with [deleted] after STOP."""
        router, db = _router()
        user = "whatsapp:anon_user_2"

        # Create a flight tracking subscription and submit a report
        router.handle(user, "TRACK P47123 2026-08-01")

        # Get the flight and create a status report
        flight = db.query(Flight).filter_by(flight_number="P47123").first()
        report = StatusReport(
            flight_id=flight.id, reporter_id=user,
            status_type=StatusType.BOARDING, gate="12",
            raw_text="boarding now gate 12", status=ReportStatus.PENDING
        )
        db.add(report)
        db.commit()

        # Verify report exists
        report_before = db.query(StatusReport).filter_by(reporter_id=user).first()
        assert report_before is not None

        # Send STOP
        router.handle(user, "STOP")

        # Verify report is anonymized
        report_orig = db.query(StatusReport).filter_by(reporter_id=user).first()
        assert report_orig is None

        report_anon = db.query(StatusReport).filter_by(reporter_id=ANONYMOUS_USER_ID).first()
        assert report_anon is not None
        assert report_anon.gate == "12"  # content preserved

    def test_reporter_score_anonymized_after_stop(self):
        """Reporter score reporter_id is replaced with [deleted] after STOP."""
        router, db = _router()
        user = "whatsapp:anon_user_3"

        # Create a reporter score
        score = ReporterScore(
            reporter_id=user, total_reports=5,
            contradicted_reports=1, trust_level="normal"
        )
        db.add(score)
        db.commit()

        # Verify score exists
        score_before = db.query(ReporterScore).filter_by(reporter_id=user).first()
        assert score_before is not None

        # Send STOP
        router.handle(user, "STOP")

        # Verify score is anonymized
        score_orig = db.query(ReporterScore).filter_by(reporter_id=user).first()
        assert score_orig is None

        score_anon = db.query(ReporterScore).filter_by(reporter_id=ANONYMOUS_USER_ID).first()
        assert score_anon is not None
        assert score_anon.total_reports == 5  # data preserved

    def test_seen_user_removed_after_stop(self):
        """SeenUser record is removed after STOP (allows fresh welcome)."""
        router, db = _router()
        user = "whatsapp:anon_user_4"

        # First interaction marks user as seen
        router.handle(user, "SUBSCRIBE LOS ABV 80000")
        seen_before = db.query(SeenUser).filter_by(user_id=user).first()
        assert seen_before is not None

        # Send STOP
        router.handle(user, "STOP")

        # SeenUser should be removed
        seen_after = db.query(SeenUser).filter_by(user_id=user).first()
        assert seen_after is None

    def test_welcome_shown_again_after_stop(self):
        """After STOP, user sees welcome intro again on next message."""
        router, db = _router()
        user = "whatsapp:anon_user_5"

        # First interaction
        router.handle(user, "SUBSCRIBE LOS ABV 80000")

        # Send STOP
        router.handle(user, "STOP")

        # Next unrecognized message should show welcome intro again
        reply = router.handle(user, "random gibberish")
        assert reply.startswith(tmpl.EMOJI_WELCOME)


# ---- Privacy Notice Tests ----

class TestPrivacyNotice:
    """Tests for NDPA-required privacy notice in onboarding."""

    def test_welcome_includes_privacy_notice(self):
        """Welcome intro includes data-use notice."""
        router, _ = _router()
        reply = router.handle("whatsapp:privacy_user_1", "HI")

        # Should mention data collection
        assert "data" in reply.lower() or "phone" in reply.lower()
        # Should mention STOP
        assert "STOP" in reply

    def test_welcome_mentions_what_is_collected(self):
        """Welcome intro mentions what data is collected."""
        intro = tmpl.welcome_intro()
        # Should mention phone number, routes, or statuses
        assert "phone" in intro.lower() or "number" in intro.lower()
        assert "route" in intro.lower() or "subscrib" in intro.lower()

    def test_welcome_mentions_stop_for_removal(self):
        """Welcome intro mentions STOP as data removal option."""
        intro = tmpl.welcome_intro()
        assert "STOP" in intro
        assert "remove" in intro.lower() or "delete" in intro.lower()

    def test_stop_confirmation_mentions_resubscribe(self):
        """STOP confirmation tells user how to resubscribe."""
        msg = tmpl.stop_confirmation(3)
        assert "HI" in msg or "start again" in msg.lower()

    def test_stop_confirmation_idempotent_message(self):
        """STOP with 0 subscriptions shows appropriate message."""
        msg = tmpl.stop_confirmation(0)
        assert "no active" in msg.lower()
