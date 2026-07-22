"""NaijaFly API.

Endpoints:
  POST /webhook/whatsapp  - Twilio inbound webhook (form-encoded: From, Body).
                            Replies with TwiML so Twilio sends the answer back.
  GET  /admin             - minimal HTML admin view
  GET  /health            - liveness
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Form, Depends, Request
from fastapi.responses import Response, HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.models.models import Base
from app.services.bot_router import BotRouter
from app.services.notifier import get_notifier
from app.admin.views import render_admin

app = FastAPI(title="NaijaFly MVP")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


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


@app.get("/admin", response_class=HTMLResponse)
def admin(db: Session = Depends(get_db)):
    return render_admin(db)
