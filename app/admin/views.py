"""Minimal HTML admin view - no auth (MVP; put behind VPN/basic-auth for pilot)."""
from sqlalchemy.orm import Session

from app.models.models import (
    Route, Flight, UserSubscription, AlertHistory,
    StatusReport, ReportStatus, ReporterScore,
)

STYLE = """
<style>
 body{font-family:sans-serif;margin:24px;max-width:1000px}
 h2{margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{border:1px solid #ddd;padding:6px 10px;text-align:left}
 th{background:#f5f5f5}
 .tag{padding:1px 8px;border-radius:10px;font-size:12px}
 .disputed{background:#ffe5e5}.confirmed{background:#e5ffe9}
 .pending{background:#eef4ff}.flagged{background:#fff3cd}
</style>
"""


def _rows(items, cols):
    if not items:
        return "<tr><td colspan='%d'><i>none</i></td></tr>" % len(cols)
    out = []
    for it in items:
        out.append("<tr>" + "".join(f"<td>{c(it)}</td>" for c in cols.values()) + "</tr>")
    return "".join(out)


def _table(title, headers, body):
    head = "".join(f"<th>{h}</th>" for h in headers)
    return f"<h2>{title}</h2><table><tr>{head}</tr>{body}</table>"


def render_admin(db: Session) -> str:
    routes = db.query(Route).all()
    fare_subs = db.query(UserSubscription).filter(
        UserSubscription.route_id.isnot(None)).all()
    flight_subs = db.query(UserSubscription).filter(
        UserSubscription.flight_id.isnot(None)).all()
    alerts = (db.query(AlertHistory)
              .order_by(AlertHistory.created_at.desc()).limit(50).all())
    disputed = (db.query(StatusReport)
                .filter(StatusReport.status == ReportStatus.DISPUTED)
                .order_by(StatusReport.created_at.desc()).limit(50).all())
    flagged = (db.query(ReporterScore)
               .filter(ReporterScore.trust_level == "flagged").all())

    def route_name(rid):
        r = db.query(Route).get(rid) if rid else None
        return f"{r.origin}->{r.destination}" if r else "-"

    def flight_name(fid):
        f = db.query(Flight).get(fid) if fid else None
        return f.flight_number if f else "-"

    html = "<html><head><title>NaijaFly Admin</title>" + STYLE + "</head><body>"
    html += "<h1>NaijaFly Admin</h1>"

    html += _table("Tracked routes", ["ID", "Origin", "Destination"], _rows(
        routes, {"a": lambda r: r.id, "b": lambda r: r.origin, "c": lambda r: r.destination}))

    html += _table("Fare subscriptions", ["User", "Route", "Target price", "Since"], _rows(
        fare_subs, {
            "a": lambda s: s.user_id,
            "b": lambda s: route_name(s.route_id),
            "c": lambda s: f"{s.target_price:,.0f}" if s.target_price else "any drop",
            "d": lambda s: s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "-"}))

    html += _table("Flight subscriptions", ["User", "Flight", "Since"], _rows(
        flight_subs, {
            "a": lambda s: s.user_id,
            "b": lambda s: flight_name(s.flight_id),
            "c": lambda s: s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "-"}))

    html += _table("Alert history (last 50)", ["When", "Type", "To", "Delivered", "Message"], _rows(
        alerts, {
            "a": lambda a: a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "-",
            "b": lambda a: a.alert_type,
            "c": lambda a: a.user_id,
            "d": lambda a: "yes" if a.delivered else "no",
            "e": lambda a: a.message}))

    html += _table("Disputed status reports", ["When", "Flight", "Reporter", "Type", "Gate", "Raw text"], _rows(
        disputed, {
            "a": lambda r: r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "-",
            "b": lambda r: flight_name(r.flight_id),
            "c": lambda r: r.reporter_id,
            "d": lambda r: r.status_type.value if r.status_type else "-",
            "e": lambda r: r.gate or "-",
            "f": lambda r: r.raw_text}))

    html += _table("Flagged reporters", ["Reporter", "Total", "Contradicted", "Rate"], _rows(
        flagged, {
            "a": lambda s: s.reporter_id,
            "b": lambda s: s.total_reports,
            "c": lambda s: s.contradicted_reports,
            "d": lambda s: f"{s.contradiction_rate:.0%}"}))

    html += "</body></html>"
    return html
