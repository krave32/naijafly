"""Outbound WhatsApp notifier.

REAL code path: uses the Twilio SDK against the WhatsApp sandbox.
Set these env vars and every push in the system goes out as a real
WhatsApp message:

    TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxx
    TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # Twilio sandbox number

If credentials are missing, the notifier degrades to CONSOLE mode:
messages are printed and recorded, so the full loop is still testable
locally. Nothing else in the codebase knows or cares which mode is active.
"""
import logging
import os

logger = logging.getLogger("naijafly.notifier")
logging.basicConfig(level=logging.INFO)


class WhatsAppNotifier:
    def __init__(self, account_sid: str = None, auth_token: str = None, from_number: str = None):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = from_number or os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        self._client = None
        self.sent = []  # in-process record (used by tests and console mode)

        if self.account_sid and self.auth_token:
            from twilio.rest import Client  # real SDK, only imported when creds exist
            self._client = Client(self.account_sid, self.auth_token)
            self.mode = "twilio"
        else:
            self.mode = "console"
            logger.warning(
                "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set - notifier in CONSOLE mode. "
                "Messages will be printed, not sent."
            )

    def send(self, to: str, body: str) -> bool:
        """Send a WhatsApp message. `to` may be '+234...' or 'whatsapp:+234...'."""
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"
        self.sent.append({"to": to, "body": body})

        if self.mode == "twilio":
            try:
                msg = self._client.messages.create(
                    from_=self.from_number, to=to, body=body
                )
                logger.info("Twilio message sent sid=%s to=%s", msg.sid, to)
                return True
            except Exception as e:
                logger.error("Twilio send failed to=%s: %s", to, e)
                return False
        else:
            logger.info("[CONSOLE-WHATSAPP] to=%s | %s", to, body)
            return True


# Singleton used by app + workers; tests construct their own instances.
_default_notifier = None

def get_notifier() -> WhatsAppNotifier:
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = WhatsAppNotifier()
    return _default_notifier
