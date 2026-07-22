"""Boarding-status aggregation - standalone, testable module.

Trust model (decoupled from fare ingestion):
  - 1 report                         -> PENDING (unconfirmed)
  - 2+ independent reports, same state -> CONFIRMED -> pushed to flight subscribers
  - conflicting states in window       -> DISPUTED (nothing silently overwritten)
    ... unless one state has a clear majority (>= threshold AND >= 2x the
    rival bucket), in which case majority wins and minority reports are
    marked DISPUTED individually.

Anti-abuse:
  - Rate limit: one report per reporter per flight per 5 minutes.
  - Reporter scoring: every report increments total_reports; reports that end
    up on the losing side of a dispute increment contradicted_reports.
    Reporters whose contradiction_rate exceeds CONTRADICTION_THRESHOLD (with a
    minimum sample size) are 'flagged': their reports are stored but EXCLUDED
    from confirmation counting and can never trigger a push on their own.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.models import (
    StatusReport, Flight, ReportStatus, StatusType,
    ReporterScore, UserSubscription, AlertHistory, PushLog,
)
from app.utils import notify_templates as tmpl

CONTRADICTION_THRESHOLD = 0.5   # >50% of your reports contradicted -> flagged
MIN_REPORTS_FOR_FLAG = 3        # don't flag anyone on tiny samples
MAJORITY_FACTOR = 2             # bucket wins dispute if >= 2x rival size


class StatusAggregationService:
    def __init__(self, db: Session, notifier=None):
        self.db = db
        self.notifier = notifier
        self.confirmation_threshold = 2
        self.time_window_minutes = 30
        self.rate_limit_minutes = 5

    # ---------- reporter scoring ----------

    def _get_score(self, reporter_id: str) -> ReporterScore:
        score = self.db.query(ReporterScore).filter_by(reporter_id=reporter_id).first()
        if not score:
            score = ReporterScore(reporter_id=reporter_id, total_reports=0,
                                  contradicted_reports=0, confirmed_reports=0)
            self.db.add(score)
            self.db.commit()
        return score

    def is_flagged(self, reporter_id: str) -> bool:
        score = self.db.query(ReporterScore).filter_by(reporter_id=reporter_id).first()
        if not score or score.total_reports < MIN_REPORTS_FOR_FLAG:
            return False
        return score.contradiction_rate > CONTRADICTION_THRESHOLD

    # ---------- intake ----------

    def add_report(self, flight_id: int, reporter_id: str,
                   status_type: StatusType, gate: str, raw_text: str):
        # Rate limit per reporter per flight
        recent = self.db.query(StatusReport).filter(
            StatusReport.flight_id == flight_id,
            StatusReport.reporter_id == reporter_id,
            StatusReport.created_at > datetime.utcnow() - timedelta(minutes=self.rate_limit_minutes),
        ).first()
        if recent:
            return None  # rate limited

        report = StatusReport(
            flight_id=flight_id, reporter_id=reporter_id,
            status_type=status_type, gate=gate, raw_text=raw_text,
            status=ReportStatus.PENDING,
        )
        self.db.add(report)

        score = self._get_score(reporter_id)
        score.total_reports = (score.total_reports or 0) + 1
        score.updated_at = datetime.utcnow()
        self.db.commit()

        self.reconcile_flight_status(flight_id)
        return report

    # ---------- reconciliation ----------

    def reconcile_flight_status(self, flight_id: int):
        window_start = datetime.utcnow() - timedelta(minutes=self.time_window_minutes)
        reports = self.db.query(StatusReport).filter(
            StatusReport.flight_id == flight_id,
            StatusReport.created_at >= window_start,
            StatusReport.status != ReportStatus.ARCHIVED,
        ).all()
        if not reports:
            return

        # Bucket by (status_type, gate). Flagged reporters' reports are kept
        # but excluded from counting.
        buckets: dict = {}
        excluded = []
        for r in reports:
            if self.is_flagged(r.reporter_id):
                excluded.append(r)
                continue
            buckets.setdefault((r.status_type, r.gate), []).append(r)

        if not buckets:
            return  # only flagged reporters spoke; never confirm from them

        # Count DISTINCT reporters per bucket (2 reports from one person != confirmation)
        def distinct(group):
            return len({r.reporter_id for r in group})

        sorted_buckets = sorted(buckets.items(), key=lambda kv: distinct(kv[1]), reverse=True)
        top_key, top_group = sorted_buckets[0]
        top_n = distinct(top_group)
        rival_n = distinct(sorted_buckets[1][1]) if len(sorted_buckets) > 1 else 0

        if len(sorted_buckets) == 1:
            # Single consistent state
            if top_n >= self.confirmation_threshold:
                self._confirm(top_group, flight_id, top_key)
            # else stay PENDING
        else:
            # Conflict. Majority-wins if top bucket is decisive.
            if top_n >= self.confirmation_threshold and top_n >= MAJORITY_FACTOR * max(rival_n, 1):
                self._confirm(top_group, flight_id, top_key)
                for _, group in sorted_buckets[1:]:
                    self._mark_contradicted(group)
            else:
                # Genuine dispute - surface it, don't overwrite
                for r in reports:
                    if r.status != ReportStatus.CONFIRMED:
                        r.status = ReportStatus.DISPUTED
        self.db.commit()

    def _mark_contradicted(self, group):
        for r in group:
            r.status = ReportStatus.DISPUTED
            score = self._get_score(r.reporter_id)
            score.contradicted_reports = (score.contradicted_reports or 0) + 1
            if score.total_reports >= MIN_REPORTS_FOR_FLAG and \
               score.contradiction_rate > CONTRADICTION_THRESHOLD:
                score.trust_level = "flagged"

    def _confirm(self, group, flight_id: int, state_key_tuple):
        newly_confirmed = False
        for r in group:
            if r.status != ReportStatus.CONFIRMED:
                newly_confirmed = True
            r.status = ReportStatus.CONFIRMED
            score = self._get_score(r.reporter_id)
            score.confirmed_reports = (score.confirmed_reports or 0) + 1
        self.db.commit()
        if newly_confirmed:
            self.push_confirmed_status(flight_id, state_key_tuple[0], state_key_tuple[1])

    # ---------- push loop (core value prop) ----------

    def push_confirmed_status(self, flight_id: int, status_type: StatusType, gate: str):
        """Push a confirmed state to every subscriber of THIS flight, once."""
        state_key = f"{status_type.value}:{gate or '-'}"
        already = self.db.query(PushLog).filter_by(
            flight_id=flight_id, state_key=state_key).first()
        if already:
            return 0  # dedupe: this exact state was already broadcast

        flight = self.db.query(Flight).get(flight_id)
        body = tmpl.status_confirmed_push(flight.flight_number, status_type, gate)

        subs = self.db.query(UserSubscription).filter_by(flight_id=flight_id).all()
        sent = 0
        for sub in subs:
            ok = self.notifier.send(sub.user_id, body) if self.notifier else False
            self.db.add(AlertHistory(
                user_id=sub.user_id, alert_type="status_confirmed",
                flight_id=flight_id, message=body, delivered=bool(ok)))
            sent += 1
        self.db.add(PushLog(flight_id=flight_id, state_key=state_key))
        self.db.commit()
        return sent
