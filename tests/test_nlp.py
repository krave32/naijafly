"""Tests for the hybrid conversational NLP layer.

Covers:
  - Pattern matcher (intent_parser.py): city mapping, intent detection,
    date extraction, price extraction, confidence scoring
  - LLM parser (llm_parser.py): mocked API responses, graceful degradation
  - Hybrid router (bot_router.py): routing priority, NL fare/subscribe,
    fallback messages, backward compatibility with commands
"""
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from app.utils.intent_parser import (
    parse_intent, resolve_iata, Intent,
    CITY_TO_IATA, _extract_cities, _extract_date, _extract_price,
    _detect_action, _is_help,
)
from app.utils.llm_parser import parse_with_llm, _build_intent, _validate_airport


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: Pattern Matcher — City / Airport Resolution
# ═══════════════════════════════════════════════════════════════════════

class TestCityToIATAMapping:
    def test_major_cities_resolve(self):
        assert resolve_iata("Lagos") == "LOS"
        assert resolve_iata("Abuja") == "ABV"
        assert resolve_iata("Port Harcourt") == "PHC"
        assert resolve_iata("Enugu") == "ENU"
        assert resolve_iata("Kano") == "KAN"
        assert resolve_iata("Calabar") == "CBQ"
        assert resolve_iata("Benin City") == "BNI"
        assert resolve_iata("Owerri") == "QOW"

    def test_iata_codes_pass_through(self):
        assert resolve_iata("LOS") == "LOS"
        assert resolve_iata("ABV") == "ABV"
        assert resolve_iata("PHC") == "PHC"

    def test_case_insensitive(self):
        assert resolve_iata("lagos") == "LOS"
        assert resolve_iata("LAGOS") == "LOS"
        assert resolve_iata("LaGoS") == "LOS"

    def test_unknown_city_returns_none(self):
        assert resolve_iata("London") is None
        assert resolve_iata("Accra") is None
        assert resolve_iata("xyz") is None

    def test_abbreviations(self):
        assert resolve_iata("PHC") == "PHC"
        assert resolve_iata("phc") == "PHC"

    def test_long_city_names(self):
        assert resolve_iata("Port Harcourt") == "PHC"
        assert resolve_iata("Benin City") == "BNI"
        assert resolve_iata("Mallam Aminu Kano") == "KAN"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: Pattern Matcher — Intent Detection
# ═══════════════════════════════════════════════════════════════════════

class TestActionDetection:
    def test_fare_query_patterns(self):
        assert _detect_action("cheap flights from Lagos to Abuja") == "fare_query"
        assert _detect_action("how much to fly to Port Harcourt") == "fare_query"
        assert _detect_action("what's the cheapest flight to Enugu") == "fare_query"
        assert _detect_action("find me a deal to Kano") == "fare_query"
        assert _detect_action("lowest fare to Calabar") == "fare_query"
        assert _detect_action("best price for Abuja") == "fare_query"
        assert _detect_action("cost to fly to Lagos") == "fare_query"
        assert _detect_action("show me flights to Benin") == "fare_query"

    def test_subscribe_patterns(self):
        assert _detect_action("alert me when prices drop for Enugu") == "subscribe"
        assert _detect_action("notify me when fares go down") == "subscribe"
        assert _detect_action("tell me when the price drops") == "subscribe"
        assert _detect_action("let me know when it gets cheaper") == "subscribe"
        assert _detect_action("when prices fall for Lagos") == "subscribe"
        assert _detect_action("watch for price drops") == "subscribe"
        assert _detect_action("keep me posted on fares") == "subscribe"
        assert _detect_action("ping me when cheaper") == "subscribe"

    def test_unknown_returns_none(self):
        assert _detect_action("the weather is nice today") is None
        assert _detect_action("random gibberish xyz") is None


class TestHelpDetection:
    def test_help_keywords(self):
        assert _is_help("help")
        assert _is_help("?")
        assert _is_help("hello")
        assert _is_help("hi")
        assert _is_help("what can you do")
        assert _is_help("how does this work")

    def test_not_help(self):
        assert not _is_help("cheap flights to Abuja")
        assert not _is_help("subscribe LOS ABV")


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: Pattern Matcher — City Extraction
# ═══════════════════════════════════════════════════════════════════════

class TestCityExtraction:
    def test_from_to_pattern(self):
        origin, dest = _extract_cities("flights from Lagos to Abuja")
        assert origin == "LOS"
        assert dest == "ABV"

    def test_x_to_y_pattern(self):
        origin, dest = _extract_cities("Lagos to Abuja")
        assert origin == "LOS"
        assert dest == "ABV"

    def test_between_and_pattern(self):
        origin, dest = _extract_cities("flights between Lagos and Abuja")
        assert origin == "LOS"
        assert dest == "ABV"

    def test_two_cities_in_order(self):
        origin, dest = _extract_cities("cheapest fare Lagos Abuja")
        assert origin == "LOS"
        assert dest == "ABV"

    def test_single_city_is_destination(self):
        origin, dest = _extract_cities("cheap flights to Enugu")
        assert origin is None
        assert dest == "ENU"

    def test_port_harcourt_not_split(self):
        """'Port Harcourt' should resolve as PHC, not 'Port' + 'Harcourt'."""
        origin, dest = _extract_cities("Lagos to Port Harcourt")
        assert origin == "LOS"
        assert dest == "PHC"

    def test_no_cities_returns_none(self):
        origin, dest = _extract_cities("hello how are you")
        assert origin is None
        assert dest is None

    def test_arrow_syntax(self):
        origin, dest = _extract_cities("LOS -> ABV")
        assert origin == "LOS"
        assert dest == "ABV"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: Pattern Matcher — Date Extraction
# ═══════════════════════════════════════════════════════════════════════

class TestDateExtraction:
    def test_iso_format(self):
        d = _extract_date("on 2026-08-15")
        assert d == datetime(2026, 8, 15)

    def test_month_day(self):
        d = _extract_date("August 15")
        assert d is not None
        assert d.month == 8
        assert d.day == 15

    def test_month_abbreviation(self):
        d = _extract_date("aug 20")
        assert d is not None
        assert d.month == 8
        assert d.day == 20

    def test_ordinal_day(self):
        d = _extract_date("15th August")
        assert d is not None
        assert d.month == 8
        assert d.day == 15

    def test_tomorrow(self):
        d = _extract_date("tomorrow")
        expected = (datetime.utcnow() + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        assert d == expected

    def test_next_week(self):
        d = _extract_date("next week")
        assert d is not None
        delta = (d - datetime.utcnow()).days
        assert 5 <= delta <= 9  # approximately 7 days

    def test_in_n_days(self):
        d = _extract_date("in 3 days")
        expected = (datetime.utcnow() + timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        assert d is not None
        assert d.date() == expected.date()

    def test_in_n_weeks(self):
        d = _extract_date("in 2 weeks")
        assert d is not None
        delta = (d - datetime.utcnow()).days
        assert 12 <= delta <= 16  # approximately 14 days

    def test_bare_month(self):
        d = _extract_date("in August")
        assert d is not None
        assert d.month == 8

    def test_no_date_returns_none(self):
        assert _extract_date("cheap flights to Abuja") is None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Pattern Matcher — Price Extraction
# ═══════════════════════════════════════════════════════════════════════

class TestPriceExtraction:
    def test_below_amount(self):
        assert _extract_price("below 80000") == 80000.0
        assert _extract_price("under 65000") == 65000.0

    def test_k_suffix(self):
        assert _extract_price("below 80k") == 80000.0
        assert _extract_price("under 50k") == 50000.0

    def test_comma_separated(self):
        assert _extract_price("below 80,000") == 80000.0

    def test_naira_symbol(self):
        assert _extract_price("₦65000") == 65000.0

    def test_ngn_prefix(self):
        assert _extract_price("NGN 70000") == 70000.0

    def test_no_price_returns_none(self):
        assert _extract_price("cheap flights to Abuja") is None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 6: Full Intent Parsing (end-to-end pattern matcher)
# ═══════════════════════════════════════════════════════════════════════

class TestParseIntent:
    def test_full_fare_query(self):
        intent = parse_intent("cheap flights from Lagos to Abuja")
        assert intent.action == "fare_query"
        assert intent.origin == "LOS"
        assert intent.destination == "ABV"
        assert intent.confidence >= 0.4

    def test_fare_query_with_date(self):
        intent = parse_intent("cheapest flight to Enugu in August")
        assert intent.action == "fare_query"
        assert intent.destination == "ENU"
        assert intent.date is not None
        assert intent.date.month == 8

    def test_subscribe_with_price(self):
        intent = parse_intent("alert me when prices drop below 80000 for Lagos to Abuja")
        assert intent.action == "subscribe"
        assert intent.origin == "LOS"
        assert intent.destination == "ABV"
        assert intent.target_price == 80000.0

    def test_help_greeting(self):
        intent = parse_intent("hello")
        assert intent.action == "help"
        assert intent.confidence == 1.0

    def test_unknown_message_low_confidence(self):
        intent = parse_intent("the weather is really nice today")
        assert intent.confidence < 0.4

    def test_is_complete_route(self):
        intent = Intent(action="fare_query", origin="LOS", destination="ABV", confidence=0.8)
        assert intent.is_complete_route()

        incomplete = Intent(action="fare_query", destination="ABV", confidence=0.6)
        assert not incomplete.is_complete_route()

    def test_confidence_scoring(self):
        # Action + both cities = 0.8
        intent = parse_intent("cheap flights from Lagos to Abuja")
        assert intent.confidence == 0.8

        # Action only (no cities) = 0.4
        intent = parse_intent("find me a deal please")
        assert intent.confidence >= 0.4


# ═══════════════════════════════════════════════════════════════════════
# SECTION 7: LLM Parser (mocked)
# ═══════════════════════════════════════════════════════════════════════

class TestLLMParser:
    def test_returns_none_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            assert parse_with_llm("cheap flights to Abuja") is None

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-123"})
    def test_parses_successful_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "action": "fare_query",
                "origin": "LOS",
                "destination": "ABV",
                "date": None,
                "target_price": None,
            })}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch("app.utils.llm_parser.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client
            intent = parse_with_llm("cheap flights to Abuja")

        assert intent is not None
        assert intent.action == "fare_query"
        assert intent.origin == "LOS"
        assert intent.destination == "ABV"
        assert intent.confidence == 0.85

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-123"})
    def test_graceful_degradation_on_api_error(self):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API timeout")

        with patch("app.utils.llm_parser.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client
            intent = parse_with_llm("something weird")

        assert intent is None

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-123"})
    def test_handles_invalid_json_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "this is not json"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch("app.utils.llm_parser.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client
            intent = parse_with_llm("something")

        assert intent is None

    def test_validate_airport(self):
        assert _validate_airport("LOS") == "LOS"
        assert _validate_airport("los") == "LOS"
        assert _validate_airport("XYZ") is None
        assert _validate_airport(None) is None
        assert _validate_airport("") is None

    def test_build_intent_null_action(self):
        result = {"action": None, "origin": None, "destination": None}
        assert _build_intent(result, "test") is None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 8: Hybrid Router Integration
# ═══════════════════════════════════════════════════════════════════════

class TestHybridRouterRouting:
    """Test that the router correctly prioritizes commands > pattern > LLM > fallback."""

    @pytest.fixture
    def router(self):
        from app.services.bot_router import BotRouter
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        return BotRouter(db)

    def test_explicit_command_still_works(self, router):
        reply = router.handle("user1", "HELP")
        assert "Araha" in reply

    def test_explicit_subscribe_still_works(self, router):
        reply = router.handle("user1", "SUBSCRIBE LOS ABV 80000")
        assert "Subscribed" in reply or "LOS" in reply

    def test_natural_language_fare_query(self, router):
        reply = router.handle("user1", "cheap flights from Lagos to Abuja")
        # Should not fall through to HELP — should route to fare handler
        assert "I didn't quite catch that" not in reply
        # Either returns fare data or "no data" (route has no fares in test DB)
        assert any(kw in reply for kw in ["LOS", "ABV", "route", "fare", "data", "Which route"])

    def test_natural_language_subscribe(self, router):
        reply = router.handle("user1", "alert me when prices drop for Lagos to Abuja")
        assert "I didn't quite catch that" not in reply
        assert any(kw in reply for kw in ["Subscribed", "LOS", "ABV", "watch"])

    def test_single_city_asks_for_origin(self, router):
        reply = router.handle("user1", "how much to fly to Enugu?")
        assert "flying from" in reply or "Where" in reply

    def test_unknown_message_gets_friendly_fallback(self, router):
        reply = router.handle("user1", "the weather is really nice today in lagos")
        # Should get the friendly fallback, not bare HELP_TEXT
        assert "I didn't quite catch that" in reply or "Araha" in reply

    def test_help_returns_natural_language_examples(self, router):
        reply = router.handle("user1", "HELP")
        assert "cheap flights from Lagos to Abuja" in reply

    def test_greeting_returns_help(self, router):
        reply = router.handle("user1", "hello")
        assert "Araha" in reply

    def test_empty_text_returns_help(self, router):
        reply = router.handle("user1", "")
        assert "Araha" in reply

    @patch("app.services.bot_router.parse_with_llm", return_value=None)
    def test_llm_disabled_graceful_fallback(self, mock_llm, router):
        """When LLM is disabled and pattern doesn't match, get friendly fallback."""
        reply = router.handle("user1", "some weird phrase that means nothing")
        assert "I didn't quite catch that" in reply or "Araha" in reply


# ═══════════════════════════════════════════════════════════════════════
# SECTION 9: Track Intent + Flight Number Extraction
# ═══════════════════════════════════════════════════════════════════════

class TestTrackIntent:
    def test_track_action_detected(self):
        assert _detect_action("track flight P47123") == "track"
        assert _detect_action("follow my flight") == "track"
        assert _detect_action("i'm on flight VK201") == "track"
        assert _detect_action("status of my flight") == "track"
        assert _detect_action("flight update P47123") == "track"
        assert _detect_action("boarding status for P47123") == "track"

    def test_flight_number_extraction(self):
        from app.utils.intent_parser import _extract_flight_number
        assert _extract_flight_number("track P47123") == "P47123"
        assert _extract_flight_number("I'm on flight VK201") == "VK201"
        assert _extract_flight_number("follow NE456") == "NE456"
        assert _extract_flight_number("P4-7123") == "P47123"
        assert _extract_flight_number("flight 7123") == "7123"
        assert _extract_flight_number("#4521") == "4521"

    def test_no_flight_number(self):
        from app.utils.intent_parser import _extract_flight_number
        assert _extract_flight_number("track my flight") is None
        assert _extract_flight_number("hello") is None

    def test_full_track_intent(self):
        intent = parse_intent("I'm on flight P47123 tomorrow")
        assert intent.action == "track"
        assert intent.flight_number == "P47123"
        assert intent.date is not None
        assert intent.confidence >= 0.4

    def test_track_without_date(self):
        intent = parse_intent("track VK201")
        assert intent.action == "track"
        assert intent.flight_number == "VK201"
        assert intent.confidence >= 0.4


# ═══════════════════════════════════════════════════════════════════════
# SECTION 10: Expanded Status Report Patterns
# ═══════════════════════════════════════════════════════════════════════

class TestExpandedStatusReports:
    def test_boarding_variants(self):
        from app.utils.parser import MessageParser
        from app.models.models import StatusType
        s, _ = MessageParser.parse("they're boarding now at gate 12")
        assert s == StatusType.BOARDING
        s, _ = MessageParser.parse("boarding announced for gate B3")
        assert s == StatusType.BOARDING
        s, _ = MessageParser.parse("we are boarding")
        assert s == StatusType.BOARDING

    def test_not_boarding_variants(self):
        from app.utils.parser import MessageParser
        from app.models.models import StatusType
        s, _ = MessageParser.parse("still waiting to board")
        assert s == StatusType.NOT_BOARDING
        s, _ = MessageParser.parse("no movement at gate 5")
        assert s == StatusType.NOT_BOARDING
        s, _ = MessageParser.parse("haven't started boarding yet")
        assert s == StatusType.NOT_BOARDING

    def test_delay_variants(self):
        from app.utils.parser import MessageParser
        from app.models.models import StatusType
        s, _ = MessageParser.parse("running late by 2 hours")
        assert s == StatusType.DELAY
        s, _ = MessageParser.parse("30 minutes late")
        assert s == StatusType.DELAY
        s, _ = MessageParser.parse("held up on the tarmac")
        assert s == StatusType.DELAY

    def test_gate_change_variants(self):
        from app.utils.parser import MessageParser
        from app.models.models import StatusType
        s, g = MessageParser.parse("gate changed to E5")
        assert s == StatusType.GATE_CHANGE
        assert g == "E5"
        s, g = MessageParser.parse("new gate is B3")
        assert s == StatusType.GATE_CHANGE
        assert g == "B3"
        s, g = MessageParser.parse("go to gate 12")
        assert s == StatusType.GATE_CHANGE
        assert g == "12"

    def test_gate_extraction_flexible(self):
        from app.utils.parser import MessageParser
        _, g = MessageParser.parse("boarding at gate 12")
        assert g == "12"
        _, g = MessageParser.parse("now at E5")
        assert g == "E5"
        _, g = MessageParser.parse("gate is now B7")
        assert g == "B7"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 11: Conversational Track via Router
# ═══════════════════════════════════════════════════════════════════════

class TestConversationalTrack:
    @pytest.fixture
    def router(self):
        from app.services.bot_router import BotRouter
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.models import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        return BotRouter(db)

    def test_natural_track_with_flight(self, router):
        reply = router.handle("user1", "I'm on flight P47123")
        assert "Tracking" in reply or "P47123" in reply

    def test_natural_track_without_flight_asks(self, router):
        reply = router.handle("user1", "track my flight")
        # Should ask for flight number since none was detected
        assert "flight" in reply.lower()

    def test_explicit_track_still_works(self, router):
        reply = router.handle("user1", "TRACK P47123 2026-08-15")
        assert "Tracking" in reply or "P47123" in reply
