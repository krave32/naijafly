"""Tests for airline name resolution and Google Flights deep links.

Verifies:
  1. resolve_airline_and_link produces correct airline names via fli_patch
  2. google_flights_url generates correct deep links
  3. The fli_patch + fare_ingestor pipeline works end-to-end
"""

import pytest


def test_google_flights_url_generates_correct_link():
    """google_flights_url should produce deep links to Google Flights."""
    from app.services.fare_ingestor import google_flights_url
    from datetime import datetime

    link = google_flights_url("LOS", "ABV", datetime(2026, 8, 15))
    assert "google.com/travel/flights" in link
    assert "LOS" in link.upper()
    assert "ABV" in link.upper()
    assert "2026-08-15" in link
    assert "NGN" in link


def test_google_flights_url_route_only():
    """Without date, deep link should not include a date."""
    from app.services.fare_ingestor import google_flights_url

    link = google_flights_url("LOS", "ABV")
    assert "google.com/travel/flights" in link
    assert "LOS" in link.upper()
    assert "ABV" in link.upper()


def test_fli_patch_airline_names_match_attribution_map():
    """After fli_patch, Airline enum values should match WEST_AFRICAN_AIRLINES."""
    from app.utils.fli_patch import apply_patches, FIXES
    from app.services.fare_ingestor import WEST_AFRICAN_AIRLINES
    import fli.models.airline as a

    apply_patches()

    for code in FIXES:
        member = getattr(a.Airline, code, None)
        if member is None:
            continue
        expected = WEST_AFRICAN_AIRLINES.get(code)
        if expected and "(defunct)" not in expected:
            assert member.value == expected, (
                f"Airline.{code}: fli says {member.value!r}, "
                f"WEST_AFRICAN_AIRLINES says {expected!r}"
            )


def test_fare_deep_link_included_in_google_fares():
    """GoogleFlightsIngestor fare dicts should include a 'link' key."""
    from app.services.fare_ingestor import GoogleFlightsIngestor
    from unittest.mock import patch, MagicMock
    from datetime import datetime

    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = True

    mock_flight = MagicMock()
    mock_flight.price = 50000
    mock_flight.primary_airline = MagicMock()
    mock_flight.primary_airline.name = "P4"
    mock_flight.primary_airline_name = "Air Peace"
    mock_leg = MagicMock()
    mock_flight.legs = [mock_leg]

    with patch("fli.search.SearchFlights") as mock_search:
        mock_instance = mock_search.return_value
        mock_instance.search.return_value = [mock_flight]
        fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))

    assert len(fares) > 0
    for fare in fares:
        assert "link" in fare
        assert fare["link"].startswith("https://www.google.com/travel/flights")


def test_mock_fare_ingestor_returns_no_link():
    """MockFareIngestor fares don't include a link (expected — only real ingestors add links)."""
    from app.services.fare_ingestor import MockFareIngestor
    from datetime import datetime

    ingestor = MockFareIngestor(seed=42)
    fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))
    for fare in fares:
        assert "link" not in fare


def test_airline_name_in_fare_source_never_contains_aerolineas():
    """After fli_patch, fare sources should never say 'Aerolineas Sosa'."""
    from app.utils.fli_patch import apply_patches
    from app.services.fare_ingestor import MockFareIngestor
    from datetime import datetime

    apply_patches()
    ingestor = MockFareIngestor(seed=42)
    fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))

    for fare in fares:
        assert "Aerolineas" not in fare.get("source", "")
        assert "Sosa" not in fare.get("source", "")


def test_safety_filter_drops_unknown_airlines():
    """Safety filter should drop fares from airlines not in the allow-list."""
    from app.services.fare_ingestor import GoogleFlightsIngestor
    from unittest.mock import patch, MagicMock
    from datetime import datetime

    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = True

    # Mock a fli result with an unknown airline code
    mock_flight = MagicMock()
    mock_flight.price = 50000
    mock_flight.primary_airline = None
    mock_flight.primary_airline_name = "Unknown Airline"

    # Create a mock leg with unknown airline code 'ZZ'
    mock_leg = MagicMock()
    mock_leg.airline.name = "ZZ"
    mock_flight.legs = [mock_leg]

    with patch("fli.search.SearchFlights") as mock_search:
        mock_instance = mock_search.return_value
        mock_instance.search.return_value = [mock_flight]

        fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))

    # Safety filter should drop the result since 'ZZ' is not in the allow-list
    assert len(fares) == 0
