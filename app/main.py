"""Araha API.

Endpoints:
  POST /webhook/whatsapp  - Twilio inbound webhook (form-encoded: From, Body).
                            Replies with TwiML so Twilio sends the answer back.
  POST /webhook/optout    - Twilio opt-out callback (STOP intercepted at platform
                            level). Triggers NDPA-compliant data deletion.
  POST /webhook/optin     - Twilio opt-in callback (START after opt-out).
  GET  /admin             - minimal HTML admin view (HTTP Basic Auth protected)
  GET  /health            - liveness
"""
import logging
import os
import secrets
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Form, Depends, Request, HTTPException, status
from fastapi.responses import Response, HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.utils.fli_patch import apply_patches as _apply_fli_patches
_apply_fli_patches()

from app.core.database import engine, get_db
from app.models.models import Base, SeenUser
from app.services.bot_router import BotRouter
from app.services.notifier import get_notifier
from app.admin.views import render_admin
from app.utils.data_deletion import delete_user_data

logger = logging.getLogger("araha.main")

# Admin credentials - read from env, no hardcoded defaults
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_USER or not ADMIN_PASSWORD:
    logger.warning(
        "ADMIN_USER / ADMIN_PASSWORD not set - /admin is running UNPROTECTED. "
        "Set these env vars before any public-facing deployment."
    )

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials with timing-safe comparison.
    Returns the username on success. If auth is disabled (no env vars), allows access."""
    if not ADMIN_USER or not ADMIN_PASSWORD:
        return "admin"
    correct_user = secrets.compare_digest(credentials.username, ADMIN_USER)
    correct_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _migrate_target_date():
    """Add target_date column to subscriptions table if it doesn't exist."""
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('subscriptions')]
        if 'target_date' not in columns:
            with engine.connect() as conn:
                conn.execute(text(
                    'ALTER TABLE subscriptions ADD COLUMN target_date TIMESTAMP'))
                conn.commit()
    except Exception:
        pass  # table may not exist yet; create_all handles that


app = FastAPI(title="Araha MVP")

# Serve the landing page at root
import pathlib
_STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent  # project root (naijafly/)


@app.get("/", response_class=HTMLResponse)
def landing_page():
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Araha</h1><p>Landing page not found.</p>", status_code=404)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # Lightweight migration: add target_date column if missing
    _migrate_target_date()


@app.get("/health")
def health():
    return {"status": "ok", "notifier_mode": get_notifier().mode}


def _twiml(message: str) -> Response:
    """Wrap a reply in TwiML so Twilio delivers it back over WhatsApp."""
    from twilio.twiml.messaging_response import MessagingResponse
    resp = MessagingResponse()
    resp.message(message)
    return Response(content=str(resp), media_type="application/xml")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...),          # e.g. "whatsapp:+2348012345678"
    Body: str = Form(""),
    db: Session = Depends(get_db),
):
    user_id = From.replace("whatsapp:", "")
    router = BotRouter(db, notifier=get_notifier())
    reply = router.handle(user_id, Body)
    return _twiml(reply)


@app.post("/webhook/optout")
async def opt_out_webhook(
    From: str = Form(...),
    db: Session = Depends(get_db),
):
    """Twilio Opt-Out Management callback.

    Called when a user sends STOP (or other platform-reserved opt-out keyword).
    Twilio intercepts these at the platform level, so they never reach
    /webhook/whatsapp. This endpoint ensures NDPA-compliant data deletion.

    Configure in Twilio Console: Messaging -> Settings -> WhatsApp Sandbox Settings
    -> Opt-out management -> set URL to this endpoint.
    """
    user_id = From.replace("whatsapp:", "")
    removed = delete_user_data(db, user_id)
    logger.info("Opt-out webhook: user=%s, removed %d subscriptions", user_id, removed)
    return {"status": "ok", "user": user_id, "subscriptions_removed": removed}


@app.post("/webhook/optin")
async def opt_in_webhook(
    From: str = Form(...),
    db: Session = Depends(get_db),
):
    """Twilio Opt-In Management callback.

    Called when a user sends START after previously opting out.
    Re-creates the SeenUser record so the welcome flow works again.
    """
    user_id = From.replace("whatsapp:", "")
    # Re-create SeenUser so the welcome intro works for returning users
    if not db.query(SeenUser).filter_by(user_id=user_id).first():
        db.add(SeenUser(user_id=user_id))
        db.commit()
    logger.info("Opt-in webhook: user=%s", user_id)
    return {"status": "ok", "user": user_id}


@app.get("/admin", response_class=HTMLResponse)
def admin(admin_user=Depends(verify_admin), db: Session = Depends(get_db)):
    return render_admin(db)
