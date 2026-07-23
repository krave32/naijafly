"""Centralized outbound message templates.

Every user-facing string the bot sends - whether a direct reply in
BotRouter or a push from FareService/StatusAggregationService - is built
here, so the emoji scheme lives in exactly one place and is easy to change.

EMOJI PROPOSAL TABLE (agent-proposed, per spec - adjust freely, it's all
centralized here so a change is a one-line edit per function):

  Message type                          Emoji   Why
  -----------------------------------   -----   ------------------------------
  Subscribe / Track confirmation         ✅      "you're set up" - a clean
                                                  positive confirmation, reused
                                                  for both SUBSCRIBE and TRACK
                                                  since both are opt-in acks.
  Fare found (FARE query result)         💰      Direct answer to "what's the
                                                  price" - money emoji reads
                                                  instantly in a preview.
  No fare/route data yet                 🔎      "still looking" - distinct
                                                  from 💰 so an empty result
                                                  never looks like a real price.
  Status report logged (pending)         📝      A note was taken, nothing
                                                  confirmed yet - deliberately
                                                  calmer than the push emojis
                                                  below so it doesn't look like
                                                  an alert.
  Rate-limited ("too fast")              ⏳      Wait signal.
  Unparsed / unclear report              ❓      Bot didn't understand.
  Fare-drop alert (push)                 📉      A price actually fell - the
                                                  "drop" is the whole point of
                                                  the message, so a downward
                                                  chart reads better here than
                                                  a plain 💰 (which is reserved
                                                  for query answers, not
                                                  unsolicited pushes).
  Boarding confirmed (push)              🛫      Plane taking off = boarding.
  Gate change confirmed (push)           🚪      Door = gate.
  Delay confirmed (push)                 ⏰      Time slipping.
  Not-boarding confirmed (push)          🕓      Still waiting, distinct clock
                                                  face from ⏰ delay.
  Other/generic status (push)            🔔      Fallback "something changed."
  HELP text                              (none)  Plain instructions - an emoji
                                                  here adds noise, not clarity.

Every emoji is applied ONCE per message, as a prefix, so it's visible in the
WhatsApp notification preview before the user opens the chat.
"""
from app.models.models import StatusType

# ---- direct bot replies (BotRouter) ----

EMOJI_SUBSCRIBED = "✅"
EMOJI_FARE_FOUND = "💰"
EMOJI_NO_DATA = "🔎"
EMOJI_REPORT_LOGGED = "📝"
EMOJI_RATE_LIMITED = "⏳"
EMOJI_UNCLEAR = "❓"

# ---- pushes (FareService / StatusAggregationService) ----

EMOJI_FARE_DROP = "📉"

STATUS_PUSH_EMOJI = {
    StatusType.BOARDING: "🛫",
    StatusType.GATE_CHANGE: "🚪",
    StatusType.DELAY: "⏰",
    StatusType.NOT_BOARDING: "🕓",
    StatusType.OTHER: "🔔",
}


def subscribed_reply(origin: str, destination: str, target: float | None,
                      date_label: str = "next 30 days") -> str:
    tgt = f" below {target:,.0f}" if target else " on any price drop"
    return (f"{EMOJI_SUBSCRIBED} Subscribed: {origin}->{destination} "
            f"({date_label}). You'll get alerts{tgt}.")


def tracking_reply(flight_number: str) -> str:
    return (f"{EMOJI_SUBSCRIBED} Tracking {flight_number}. You'll get confirmed "
            f"boarding/gate/delay updates. At the airport? Text what you see, "
            f"e.g. 'boarding now gate 12'.")


def fare_found_reply(origin: str, destination: str, price_local: float,
                     currency_local: str, price_usd: float, source: str,
                     date_label: str = "next 30 days") -> str:
    return (f"{EMOJI_FARE_FOUND} Cheapest {origin}->{destination} ({date_label}): "
            f"{price_local:,.0f} {currency_local} (~${price_usd:,.2f} USD) on {source}")


def no_route_reply(origin: str, destination: str) -> str:
    return (f"{EMOJI_NO_DATA} No tracked fares yet for {origin}->{destination}. "
            f"SUBSCRIBE to start tracking.")


def no_fare_data_reply(origin: str, destination: str) -> str:
    return f"{EMOJI_NO_DATA} No fare data yet for {origin}->{destination}. Check back soon."


def report_logged_reply(status_label: str, gate: str | None, flight_number: str) -> str:
    gate_part = f" gate {gate}" if gate else ""
    return (f"{EMOJI_REPORT_LOGGED} Got it - logged '{status_label}'{gate_part} "
            f"for {flight_number}. It goes out to other passengers once a "
            f"second person confirms.")


def rate_limited_reply() -> str:
    return f"{EMOJI_RATE_LIMITED} You're reporting too fast - wait a few minutes before your next update."


def unclear_report_reply() -> str:
    return (f"{EMOJI_UNCLEAR} Didn't catch that. Report like: 'boarding now gate 12', "
            f"'2hr delay announced', 'gate changed to B3'. Or HELP for commands.")


def fare_drop_push(origin: str, destination: str, price: float, currency: str,
                   usd: float, source: str, date_label: str = "") -> str:
    date_part = f" ({date_label})" if date_label else ""
    return (f"{EMOJI_FARE_DROP} [NaijaFly] Price drop {origin}->{destination}{date_part}: "
            f"{price:,.0f} {currency} (~${usd:,.2f} USD) on {source}.")


def status_confirmed_push(flight_number: str, status_type: StatusType, gate: str | None) -> str:
    emoji = STATUS_PUSH_EMOJI.get(status_type, STATUS_PUSH_EMOJI[StatusType.OTHER])
    label = {
        StatusType.BOARDING: f"BOARDING now{f' at gate {gate}' if gate else ''}",
        StatusType.GATE_CHANGE: f"GATE CHANGED{f' to {gate}' if gate else ''}",
        StatusType.DELAY: "DELAY announced",
        StatusType.NOT_BOARDING: "NOT boarding yet",
        StatusType.OTHER: "Status update",
    }[status_type]
    return (f"{emoji} [NaijaFly] {flight_number}: {label}. "
            f"Confirmed by 2+ passengers at the airport.")
