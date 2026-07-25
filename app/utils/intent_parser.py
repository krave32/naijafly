"""Hybrid intent parser — pattern-matching layer for natural language messages.

Extracts structured intents from casual English / Nigerian Pidgin phrases like:
  "cheap flights from Lagos to Abuja"
  "how much to fly to Port Harcourt?"
  "alert me when prices drop for Enugu"
  "what's the cheapest flight to Kano in August?"

Covers ~80% of expected user phrasings. Messages that don't match any
pattern fall through to the LLM parser (or back to HELP_TEXT).
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# ── City / airport name → IATA mapping ──────────────────────────────────
# Covers all Nigerian domestic airports in scope, plus common spellings,
# abbreviations, and Nigerian Pidgin variants.
CITY_TO_IATA: dict[str, str] = {}

_AIRPORT_MAP: list[tuple[list[str], str]] = [
    (["lagos", "los", "murtala muhammed"],                                    "LOS"),
    (["abuja", "abv", "nnamdi azikiwe"],                                      "ABV"),
    (["port harcourt", "phc", "ph city", "portharcourt", "port-harcourt"],    "PHC"),
    (["enugu", "enu", "akanu ibiam"],                                          "ENU"),
    (["benin", "benin city", "bni"],                                           "BNI"),
    (["kano", "kan", "mallam aminu kano"],                                     "KAN"),
    (["calabar", "cbq", "margaret ekpo"],                                      "CBQ"),
    (["ilorin", "ilr"],                                                        "ILR"),
    (["owerri", "qow", "sam mbakwe", "oweri"],                                 "QOW"),
    (["asaba", "abb", "akwa"],                                                 "ABB"),
    (["uyo", "quotation", "quotation airport", "quo", "akwa ibom"],           "QUO"),
    (["sokoto", "sko", "sadiq abubakar"],                                      "SKO"),
    (["yola", "yol"],                                                          "YOL"),
    (["maiduguri", "miu"],                                                     "MIU"),
    (["akure", "akr"],                                                         "AKR"),
]

for _names, _iata in _AIRPORT_MAP:
    for _name in _names:
        CITY_TO_IATA[_name.lower()] = _iata

# Pre-build a regex that matches any city name (longest-first to avoid
# "port" matching before "port harcourt")
_CITY_NAMES_SORTED = sorted(CITY_TO_IATA.keys(), key=len, reverse=True)
_CITY_PATTERN = "|".join(re.escape(name) for name in _CITY_NAMES_SORTED)
_CITY_RE = re.compile(rf"\b({_CITY_PATTERN})\b", re.IGNORECASE)


# ── Month name → number mapping ────────────────────────────────────────
_MONTHS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


# ── Intent data class ──────────────────────────────────────────────────
@dataclass
class Intent:
    """Structured representation of a parsed user message."""
    action: str  # "fare_query" | "subscribe" | "help" | "track" | None
    origin: Optional[str] = None       # IATA code
    destination: Optional[str] = None  # IATA code
    date: Optional[datetime] = None
    target_price: Optional[float] = None
    confidence: float = 0.0            # 0.0–1.0
    raw_text: str = ""

    def is_complete_route(self) -> bool:
        """True if both origin and destination are resolved."""
        return self.origin is not None and self.destination is not None


# ── Public API ─────────────────────────────────────────────────────────

def parse_intent(text: str) -> Intent:
    """Parse a natural-language message into an Intent.

    Returns an Intent with confidence > 0 if a pattern matched,
    or confidence=0 / action=None if nothing matched (caller should
    fall through to LLM or HELP).
    """
    raw = text.strip()
    lower = raw.lower()

    # ── HELP detection ─────────────────────────────────────────────────
    if _is_help(lower):
        return Intent(action="help", confidence=1.0, raw_text=raw)

    # ── Detect intent keyword ──────────────────────────────────────────
    action = _detect_action(lower)

    # ── Extract cities ─────────────────────────────────────────────────
    origin, destination = _extract_cities(lower)

    # ── Extract date ───────────────────────────────────────────────────
    date = _extract_date(lower)

    # ── Extract target price ───────────────────────────────────────────
    target_price = _extract_price(lower)

    # ── Score confidence ───────────────────────────────────────────────
    confidence = _score_confidence(action, origin, destination)

    # If we got nothing useful, return empty intent (triggers fallback)
    if action is None and origin is None and destination is None:
        return Intent(action=None, confidence=0.0, raw_text=raw)

    return Intent(
        action=action,
        origin=origin,
        destination=destination,
        date=date,
        target_price=target_price,
        confidence=confidence,
        raw_text=raw,
    )


# ── Internal helpers ───────────────────────────────────────────────────

def _is_help(text: str) -> bool:
    return text.strip().lower() in {
        "help", "?", "hello", "hi", "hey", "sup",
        "what can you do", "how does this work", "commands",
        "menu", "options", "what do you do",
    }


def _detect_action(text: str) -> Optional[str]:
    """Determine the user's intent from keywords."""
    # Subscribe / alert patterns
    subscribe_patterns = [
        r"\balert\s*(me|us)?\b",
        r"\bnotify\s*(me|us)?\b",
        r"\btell\s*me\s*when\b",
        r"\blet\s*me\s*know\s*when\b",
        r"\bwhen\s*price[s]?\s*(drop|go\s*down|fall|decrease|reduce)\b",
        r"\bwhen\s*(it|fare|flight)\s*(drop|go\s*down|fall|decrease|reduce)\b",
        r"\bprice\s*(drop|alert|watch|monitor|notify)\b",
        r"\bwatch\s*(for|the)?\b",
        r"\bsubscribe\b",
        r"\bkeep\s*me\s*(posted|updated|informed)\b",
        r"\bping\s*me\b",
    ]
    for pat in subscribe_patterns:
        if re.search(pat, text):
            return "subscribe"

    # Fare query patterns
    fare_patterns = [
        r"\b(cheap|cheapest|lowest|best)\s*(flight|fare|price|ticket|deal)",
        r"\bhow\s*much\b",
        r"\bcost\s*(of|to|for)?\b",
        r"\bprice\s*(of|for|to|from)?\b",
        r"\bfare\s*(to|from|for|between)?\b",
        r"\bflight\s*(to|from|for|between)?\b",
        r"\bfind\s*(me\s*)?(a\s*)?(flight|fare|deal|ticket)",
        r"\blook\s*(up|for)?\b",
        r"\bsearch\s*(for)?\b",
        r"\bshow\s*(me)?\b",
        r"\bwhat.*fly\b",
        r"\bfly\s*to\b",
        r"\bgoing\s*to\b",
        r"\btrip\s*to\b",
        r"\btravel\s*to\b",
    ]
    for pat in fare_patterns:
        if re.search(pat, text):
            return "fare_query"

    return None


def _extract_cities(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract origin and destination IATA codes from text.

    Strategy:
    1. Look for directional phrases ("from X to Y", "X to Y")
    2. Fall back to first two city matches in order
    """
    # Try directional patterns first
    directionals = [
        # "from Lagos to Abuja"
        rf"(?:from|leaving|departing|out\s*of)\s+({_CITY_PATTERN})\s+(?:to|going\s*to|heading\s*to|->|→)\s+({_CITY_PATTERN})",
        # "Lagos to Abuja"
        rf"({_CITY_PATTERN})\s+(?:to|->|→|-|going\s*to|heading\s*to)\s+({_CITY_PATTERN})",
        # "between Lagos and Abuja"
        rf"(?:between|from)\s+({_CITY_PATTERN})\s+(?:and|&|↔)\s+({_CITY_PATTERN})",
    ]
    for pat in directionals:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            city_a = CITY_TO_IATA.get(m.group(1).lower().strip())
            city_b = CITY_TO_IATA.get(m.group(2).lower().strip())
            if city_a and city_b:
                return city_a, city_b

    # Fallback: find all city mentions in order, take first two
    matches = list(_CITY_RE.finditer(text))
    if len(matches) >= 2:
        city_a = CITY_TO_IATA.get(matches[0].group(1).lower().strip())
        city_b = CITY_TO_IATA.get(matches[1].group(1).lower().strip())
        return city_a, city_b

    # Single city — treat as destination (user's current location is unknown)
    if len(matches) == 1:
        dest = CITY_TO_IATA.get(matches[0].group(1).lower().strip())
        return None, dest

    return None, None


def _extract_date(text: str) -> Optional[datetime]:
    """Extract a date from natural language.

    Handles:
    - "2026-08-15" (ISO format)
    - "August 15", "aug 15", "15th of August"
    - "next week", "next month", "tomorrow", "this weekend"
    - "in 2 weeks", "in 3 days"
    """
    now = datetime.utcnow()

    # ISO format: 2026-08-15
    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            pass

    # "tomorrow"
    if "tomorrow" in text:
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)

    # "this weekend" / "next weekend"
    if "weekend" in text:
        # Next Saturday
        days_until_sat = (5 - now.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        if "next" in text:
            days_until_sat += 7
        return (now + timedelta(days=days_until_sat)).replace(hour=0, minute=0, second=0)

    # "next week"
    if "next week" in text:
        return (now + timedelta(days=7)).replace(hour=0, minute=0, second=0)

    # "next month"
    if "next month" in text:
        next_m = now.month + 1 if now.month < 12 else 1
        return datetime(now.year if now.month < 12 else now.year + 1, next_m, 1)

    # "in N days/weeks"
    m = re.search(r"\bin\s+(\d+)\s+(day|days|week|weeks)\b", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        delta = timedelta(days=n if unit == "day" else n * 7)
        return (now + delta).replace(hour=0, minute=0, second=0, microsecond=0)

    # Build month name alternation list (longest first to match "september" before "sep")
    _month_names_sorted = sorted(_MONTHS.keys(), key=len, reverse=True)
    _month_alt = "|".join(re.escape(mn) for mn in _month_names_sorted)

    # "August 15", "aug 15", "15th August", "15 of August"
    m = re.search(
        rf"\b({_month_alt})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b|"
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_month_alt})\b",
        text, re.IGNORECASE)
    if m:
        if m.group(1) and m.group(2):
            month_name, day = m.group(1).lower(), int(m.group(2))
        else:
            day, month_name = int(m.group(3)), m.group(4).lower()
        month = _MONTHS.get(month_name)
        if month:
            year = now.year if month >= now.month else now.year + 1
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    # Bare month name ("in August", "for December") → first day of that month
    for month_name in _month_names_sorted:
        if re.search(rf"\b{re.escape(month_name)}\b", text, re.IGNORECASE):
            month_num = _MONTHS[month_name]
            year = now.year if month_num >= now.month else now.year + 1
            return datetime(year, month_num, 1)

    return None


def _extract_price(text: str) -> Optional[float]:
    """Extract a target price from text.

    Handles: "80000", "80,000", "below 80k", "under 80000 naira", "₦65000"
    """
    # "below/under/less than 80000" or "below 80k"
    m = re.search(r"\b(?:below|under|less\s*than|beneath|cheaper\s*than|@?)"
                  r"\s*(?:₦|ngn|naira)?\s*"
                  r"(\d{2,7}(?:,\d{3})*)\s*(k)?\b", text, re.IGNORECASE)
    if m:
        price_str = m.group(1).replace(",", "")
        price = float(price_str)
        if m.group(2):  # "k" suffix
            price *= 1000
        return price

    # ₦65000 or NGN 65000
    m = re.search(r"(?:₦|ngn)\s*(\d{2,7}(?:,\d{3})*)", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    return None


def _score_confidence(action, origin, destination) -> float:
    """Score how confident we are in this parse (0.0–1.0)."""
    score = 0.0
    if action:
        score += 0.4
    if origin and destination:
        score += 0.4
    elif origin or destination:
        score += 0.2
    return min(score, 1.0)


def resolve_iata(name: str) -> Optional[str]:
    """Resolve a city name or IATA code to an IATA code.

    Handles both "Lagos" → "LOS" and "LOS" → "LOS".
    """
    lookup = name.lower().strip()
    # Already an IATA code?
    upper = name.upper().strip()
    all_iata = set(CITY_TO_IATA.values())
    if upper in all_iata:
        return upper
    return CITY_TO_IATA.get(lookup)
