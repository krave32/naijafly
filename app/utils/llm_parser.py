"""LLM-based intent parser — fallback for messages that pattern matching misses.

Sends the user's message to an OpenAI-compatible chat API and extracts a
structured intent JSON.  Gracefully degrades: if no API key is configured
or the call fails, returns None so the caller can fall back to HELP_TEXT.

Requires: OPENAI_API_KEY env var (or OPENAI_BASE_URL + OPENAI_API_KEY for
self-hosted / compatible endpoints like Together, Groq, OpenRouter).
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.utils.intent_parser import Intent, resolve_iata

logger = logging.getLogger("araha.llm_parser")

# Valid IATA codes for Nigerian domestic airports in scope
VALID_AIRPORTS = {
    "LOS", "ABV", "PHC", "ENU", "BNI", "KAN", "CBQ", "ILR",
    "QOW", "ABB", "QUO", "SKO", "YOL", "MIU", "AKR",
}

SYSTEM_PROMPT = f"""You are an intent parser for a Nigerian domestic flight fare tracker called Araha.
The user sends you WhatsApp messages. Extract the intent as JSON.

Valid airports (IATA codes): {', '.join(sorted(VALID_AIRPORTS))}
Today's date: {{today}}

Return ONLY a JSON object with these fields:
- "action": one of "fare_query", "subscribe", "help", "track", "airline_request", "airline_list", or null
- "origin": IATA airport code (3 letters) or null
- "destination": IATA airport code (3 letters) or null
- "date": ISO date string (YYYY-MM-DD) or null
- "target_price": number (in NGN) or null
- "airline": airline name the user wants tracked (string) or null

Rules:
- "fare_query" = user wants to know the cheapest/current fare price
- "subscribe" = user wants alerts when prices drop
- "help" = user is asking what the bot can do, or greeting
- "track" = user wants boarding/status updates for a specific flight
- "airline_request" = user wants us to track/add a specific AIRLINE (e.g. "can you track Xejet?") — set "airline"
- "airline_list" = user asks which airlines we track/cover
- If the user mentions only one city, treat it as the destination (origin unknown)
- Convert city names to IATA codes: Lagos=LOS, Abuja=ABV, Port Harcourt=PHC,
  Enugu=ENU, Benin=BNI, Kano=KAN, Calabar=CBQ, Ilorin=ILR, Owerri=QOW
- Convert relative dates: "next week"=7 days, "tomorrow"=+1 day,
  "in August"=first day of August, etc.
- If the message is unclear or unrelated, set action to null
"""


def parse_with_llm(text: str) -> Optional[Intent]:
    """Parse a message using an LLM API. Returns None on failure or if unavailable."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("OPENAI_API_KEY not set — LLM parser disabled")
        return None

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.format(today=today)

    try:
        client = httpx.Client(timeout=10.0)
        resp = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("LLM API call failed: %s", e)
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass

    # Parse the response
    try:
        content = data["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        result = json.loads(content.strip())
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning("LLM response parse error: %s (raw: %s)", e, content[:200])
        return None

    return _build_intent(result, text)


def _build_intent(result: dict, raw_text: str) -> Optional[Intent]:
    """Convert LLM JSON response into an Intent."""
    action = result.get("action")
    if action not in {"fare_query", "subscribe", "help", "track",
                      "airline_request", "airline_list", None}:
        logger.warning("LLM returned unknown action: %s", action)
        action = None

    if action is None:
        return None

    origin = _validate_airport(result.get("origin"))
    destination = _validate_airport(result.get("destination"))

    date = None
    date_str = result.get("date")
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    target_price = result.get("target_price")
    if target_price is not None:
        try:
            target_price = float(target_price)
        except (ValueError, TypeError):
            target_price = None

    confidence = 0.85 if action else 0.0

    airline = result.get("airline")
    if airline is not None and not isinstance(airline, str):
        airline = None

    return Intent(
        action=action,
        origin=origin,
        destination=destination,
        date=date,
        target_price=target_price,
        airline=airline.strip().title() if airline else None,
        confidence=confidence,
        raw_text=raw_text,
    )


def _validate_airport(code: Optional[str]) -> Optional[str]:
    """Return the code only if it's in our valid airport set."""
    if code and isinstance(code, str):
        upper = code.upper().strip()
        if upper in VALID_AIRPORTS:
            return upper
    return None
