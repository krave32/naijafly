"""Araha API.

Endpoints:
  POST /webhook/whatsapp  - Twilio inbound webhook (form-encoded: From, Body).
                            Replies with TwiML so Twilio sends the answer back.
  GET  /admin             - minimal HTML admin view (HTTP Basic Auth protected)
  GET  /health            - liveness
"""
import base64
import logging
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Form, Depends, Request
from fastapi.responses import Response, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.models.models import Base
from app.services.bot_router import BotRouter
from app.services.notifier import get_notifier
from app.admin.views import render_admin

logger = logging.getLogger("araha.main")

# Admin credentials - read from env, no hardcoded defaults
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_USER or not ADMIN_PASSWORD:
    logger.warning(
        "ADMIN_USER / ADMIN_PASSWORD not set - /admin is running UNPROTECTED. "
        "Set these env vars before any public-facing deployment."
    )

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


def _check_admin_auth(request: Request) -> bool:
    """Validate HTTP Basic Auth credentials for admin routes.

    Returns True if credentials are valid, or if auth is disabled (no env vars set).
    Returns False if credentials are set but invalid.
    """
    if not ADMIN_USER or not ADMIN_PASSWORD:
        return True  # auth disabled - warning logged at startup

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        user, password = decoded.split(":", 1)
        return user == ADMIN_USER and password == ADMIN_PASSWORD
    except Exception:
        return False


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, db: Session = Depends(get_db)):
    if not _check_admin_auth(request):
        return HTMLResponse(
            "<h1>401 Unauthorized</h1><p>Invalid credentials.</p>",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Araha Admin"'}
        )
    return render_admin(db)
