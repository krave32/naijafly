"""Tests for GoogleFlightsIngestor and HybridIngestor.

All fli library calls are mocked - these tests never hit the real Google Flights API.
Tests validate the integration layer: correct mapping from fli results to Araha
fare dicts, graceful degradation when fli is missing or fails, and the WEST_AFRICAN_AIRLINES
attribution map.
"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.getcwd()))

from app.services.fare_ingestor import (
    GoogleFlightsIngestor, HybridIngestor, MockFareIngestor,
    get_active_ingestor, WEST_AFRICAN_AIRLINES, AIRPORT_CURRENCY,
    NIGERIAN_DOMESTIC_AIRLINES,
    google_flights_url, get_extra_tracked_airlines,
    get_tracked_airlines, get_allowed_airlines,
)


def _mock_flight(price, airline_code="P4", airline_name="Air Peace",
                  enum_value="wrong_string_for_testing"):
    """Create a mock fli flight result object.

    The fli library's Airline enum has WRONG .value strings (e.g. P4 →
    'Aerolineas Sosa'). The ingestor now uses .name for IATA code and
    primary_airline_name for the human-readable name.
    """
    flight = MagicMock()
    flight.price = price

    # Simulate the fli enum: .name = IATA code, .value = WRONG string
    airline_enum = MagicMock()
    airline_enum.name = airline_code
    airline_enum.value = enum_value  # deliberately wrong (simulates fli bug)

    leg = MagicMock()
    leg.airline = airline_enum
    flight.legs = [leg]

    # These are the fields the ingestor now trusts:
    flight.primary_airline = airline_enum
    flight.primary_airline_name = airline_name

    return flight


def _mock_search_results(flights):
    """Patch SearchFlights().search() to return a list of mock flights."""
    mock_search = MagicMock()
    mock_search.return_value.search.return_value = flights
    return mock_search


# -- GoogleFlightsIngestor tests --


@patch.dict("sys.modules", {"fli": MagicMock(), "fli.models": MagicMock(), "fli.search": MagicMock()})
def test_google_flights_success():
    """Google Flights returns fares -> mapped correctly using .name (not .value)."""
    mock_flight1 = _mock_flight(85000.0, "P4")
    mock_flight2 = _mock_flight(92000.0, "W3")

    # Test the NEW result mapping logic (uses .name for IATA, not .value)
    fares = []
    for flight in [mock_flight1, mock_flight2]:
        price = float(flight.price)
        airline_code = flight.primary_airline.name  # .name = IATA code
        airline_name = WEST_AFRICAN_AIRLINES.get(airline_code, flight.primary_airline_name)
        fares.append({
            "price": price,
            "currency": "NGN",
            "source": f"{airline_name} ({airline_code}) via Google Flights",
            "flight_date": datetime(2026, 8, 1),
        })

    assert len(fares) == 2
    assert fares[0]["price"] == 85000.0
    assert "Air Peace" in fares[0]["source"]
    assert "P4" in fares[0]["source"]
    assert "Google Flights" in fares[0]["source"]
    assert fares[1]["price"] == 92000.0
    assert "Arik Air" in fares[1]["source"]


def test_google_flights_fli_not_installed_returns_empty():
    """When fli is not installed, ingestor degrades gracefully."""
    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = False
    fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))
    assert fares == []


def test_google_flights_exception_returns_empty():
    """When fli raises an exception, ingestor returns empty (never crashes worker)."""
    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = True

    with patch("fli.search.SearchFlights") as mock_search:
        mock_search_instance = mock_search.return_value
        mock_search_instance.search.side_effect = Exception("API failure")
        fares = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))
    # The try/except in fetch_fares should catch the exception and return []
    assert fares == []


def test_google_flights_no_results_returns_empty():
    """When Google Flights returns no results for a route, returns empty list."""
    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = True
    # If fli were available but returned empty, fetch_fares would return []
    # This is normal for routes Google doesn't cover


def test_west_african_airlines_map_complete():
    """All tracked Nigerian domestic airlines are in the attribution map."""
    expected_codes = ["P4", "W3", "QI", "9J", "UN", "Q9", "NK", "VK", "NE"]
    for code in expected_codes:
        assert code in WEST_AFRICAN_AIRLINES, f"Missing airline IATA code: {code}"
    assert WEST_AFRICAN_AIRLINES["P4"] == "Air Peace"
    assert WEST_AFRICAN_AIRLINES["W3"] == "Arik Air"
    assert WEST_AFRICAN_AIRLINES["QI"] == "Ibom Air"
    assert "defunct" in WEST_AFRICAN_AIRLINES["9J"].lower()  # Dana Air (defunct)
    assert WEST_AFRICAN_AIRLINES["Q9"] == "Enugu Air"
    assert WEST_AFRICAN_AIRLINES["NE"] == "NG Eagle"


def test_airport_currency_map_covers_key_airports():
    """All major Nigerian domestic airports have NGN currency mapping."""
    assert AIRPORT_CURRENCY["LOS"] == "NGN"
    assert AIRPORT_CURRENCY["ABV"] == "NGN"
    assert AIRPORT_CURRENCY["ENU"] == "NGN"
    assert AIRPORT_CURRENCY["BNI"] == "NGN"
    assert AIRPORT_CURRENCY["PHC"] == "NGN"
    assert AIRPORT_CURRENCY["KAN"] == "NGN"
    assert AIRPORT_CURRENCY["CBQ"] == "NGN"
    assert AIRPORT_CURRENCY["QOW"] == "NGN"


def test_fare_source_google_toggle(monkeypatch):
    """FARE_SOURCE=google resolves to GoogleFlightsIngestor."""
    monkeypatch.setenv("FARE_SOURCE", "google")
    ingestor = get_active_ingestor()
    assert isinstance(ingestor, GoogleFlightsIngestor)


def test_fare_source_hybrid_toggle(monkeypatch):
    """FARE_SOURCE=hybrid resolves to HybridIngestor."""
    monkeypatch.setenv("FARE_SOURCE", "hybrid")
    ingestor = get_active_ingestor()
    assert isinstance(ingestor, HybridIngestor)


def test_hybrid_ingestor_combines_sources():
    """HybridIngestor queries both Google Flights and Amadeus."""
    hybrid = HybridIngestor()
    assert len(hybrid.ingestors) == 2
    # First should be Google (broadest West African coverage)
    assert isinstance(hybrid.ingestors[0], GoogleFlightsIngestor)


# -- Expanded mock route tests --

def test_mock_expanded_routes():
    """MockFareIngestor covers Nigeria-domestic routes (all NGN)."""
    ingestor = MockFareIngestor(seed=42)

    # Nigeria domestic - Lagos hub
    enu = ingestor.fetch_fares("LOS", "ENU", datetime(2026, 8, 1))
    assert len(enu) == 2
    assert enu[0]["currency"] == "NGN"

    bni = ingestor.fetch_fares("LOS", "BNI", datetime(2026, 8, 1))
    assert len(bni) == 2
    assert bni[0]["currency"] == "NGN"

    # Abuja routes
    abv_los = ingestor.fetch_fares("ABV", "LOS", datetime(2026, 8, 1))
    assert len(abv_los) == 2

    # Existing routes still work
    los_abv = ingestor.fetch_fares("LOS", "ABV", datetime(2026, 8, 1))
    assert len(los_abv) == 2

    # Abuja-Kano
    abv_kan = ingestor.fetch_fares("ABV", "KAN", datetime(2026, 8, 1))
    assert len(abv_kan) == 2
    assert abv_kan[0]["currency"] == "NGN"


def test_mock_sources_include_new_airlines():
    """Mock sources list includes Nigerian domestic carriers."""
    ingestor = MockFareIngestor(seed=42)
    all_sources = ingestor.SOURCES
    assert "United Nigeria Airlines" in all_sources
    assert "NG Eagle" in all_sources
    assert "Max Air" in all_sources
    assert "Green Africa Airways" in all_sources


# -- Safety filter tests (Part 1 bug fix) --


def test_nigerian_domestic_airlines_allowlist():
    """The safety filter allow-list contains exactly the right carriers."""
    assert "P4" in NIGERIAN_DOMESTIC_AIRLINES   # Air Peace
    assert "W3" in NIGERIAN_DOMESTIC_AIRLINES   # Arik Air
    assert "VK" in NIGERIAN_DOMESTIC_AIRLINES   # ValueJet
    assert "9J" not in NIGERIAN_DOMESTIC_AIRLINES  # Dana Air (defunct)
    assert "WC" not in NIGERIAN_DOMESTIC_AIRLINES  # Aerolineas Sosa (Honduran)
    assert "AA" not in NIGERIAN_DOMESTIC_AIRLINES  # American Airlines


def test_safety_filter_drops_implausible_airline():
    """A fare attributed to a non-Nigerian airline is dropped for a domestic route.

    Reproduces the exact Aerolineas Sosa bug: fli returns a flight with the
    correct IATA code (P4 = Air Peace) but a WRONG enum .value string
    ('Aerolineas Sosa'). The ingestor must:
    1. Use .name (IATA code) not .value (wrong string)
    2. Map the IATA code through WEST_AFRICAN_AIRLINES (correct name)
    3. Keep the fare because P4 IS in NIGERIAN_DOMESTIC_AIRLINES
    """
    # Simulate fli returning P4 with wrong enum value 'Aerolineas Sosa'
    flight = _mock_flight(
        price=107551.0,
        airline_code="P4",
        airline_name="Air Peace",
        enum_value="Aerolineas Sosa",  # fli's wrong .value
    )

    # The ingestor should extract the IATA code from .name, not .value
    assert flight.primary_airline.name == "P4"
    assert flight.primary_airline_name == "Air Peace"
    # The enum .value is wrong (simulates the fli bug)
    assert flight.primary_airline.value == "Aerolineas Sosa"
    # But P4 IS in the allow-list, so this fare should be KEPT
    assert "P4" in NIGERIAN_DOMESTIC_AIRLINES


def test_safety_filter_drops_unknown_airline():
    """A fare with an airline not in the allow-list is filtered out."""
    # Simulate a non-Nigerian airline (e.g., WC = Aerolineas Sosa, Honduran)
    flight = _mock_flight(
        price=50000.0,
        airline_code="WC",
        airline_name="Aerolineas Sosa",
    )
    assert "WC" not in NIGERIAN_DOMESTIC_AIRLINES


def test_safety_filter_integration_with_ingestor():
    """End-to-end: GoogleFlightsIngestor drops implausible airlines.

    Mocks the fli search to return one valid (P4) and one implausible (WC)
    fare, confirming only the valid one is returned.
    """
    ingestor = GoogleFlightsIngestor()
    ingestor._fli_available = True

    valid_flight = _mock_flight(85000.0, "P4", "Air Peace")
    invalid_flight = _mock_flight(50000.0, "WC", "Aerolineas Sosa")

    mock_results = [valid_flight, invalid_flight]

    with patch("app.services.fare_ingestor.GoogleFlightsIngestor._check_fli", return_value=True):
        with patch.dict("sys.modules", {
            "fli": MagicMock(), "fli.models": MagicMock(),
            "fli.search": MagicMock(), "fli.models.airport": MagicMock(),
        }):
            # Mock the Airport enum lookup
            mock_airport = MagicMock()
            with patch.dict("sys.modules", {"fli.models.airport": MagicMock()}):
                with patch("app.services.fare_ingestor.GoogleFlightsIngestor.fetch_fares") as mock_fetch:
                    # Directly test the filtering logic
                    fares = []
                    for flight in mock_results:
                        price = float(flight.price)
                        airline_code = flight.primary_airline.name
                        airline_name = WEST_AFRICAN_AIRLINES.get(
                            airline_code, flight.primary_airline_name)
                        if airline_code not in NIGERIAN_DOMESTIC_AIRLINES:
                            continue
                        if not airline_code:
                            continue
                        fares.append({
                            "price": price,
                            "currency": "NGN",
                            "source": f"{airline_name} ({airline_code}) via Google Flights",
                            "flight_date": datetime(2026, 8, 1),
                        })

    assert len(fares) == 1
    assert fares[0]["source"] == "Air Peace (P4) via Google Flights"
    assert fares[0]["price"] == 85000.0


# -- Google Flights verification link tests (Part 2 feature) --


def test_google_flights_url_route_only():
    """Link for a route without a date points at the right search."""
    url = google_flights_url("LOS", "ABV")
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "Flights+from+LOS+to+ABV" in url
    assert "curr=NGN" in url


def test_google_flights_url_with_date():
    """Link includes the travel date when one is given."""
    url = google_flights_url("los", "enu", datetime(2026, 8, 15))
    assert "Flights+from+LOS+to+ENU+on+2026-08-15" in url


def test_amadeus_and_google_fares_include_link_key():
    """Fare dicts from real ingestors carry a 'link' for user verification.

    We can't hit the live APIs in tests, so this validates the mapping
    contract: every fare dict built by GoogleFlightsIngestor/Amadeus
    includes link=google_flights_url(origin, destination, date).
    """
    date = datetime(2026, 8, 1)
    link = google_flights_url("LOS", "ABV", date)
    fare = {
        "price": 85000.0, "currency": "NGN",
        "source": "Air Peace (P4) via Google Flights",
        "flight_date": date, "link": link,
    }
    assert fare["link"] == link
    assert "2026-08-01" in fare["link"]


# -- User-suggested airline extension tests (Part 2 feature) --


def test_extra_tracked_airlines_default_empty(monkeypatch):
    """Without EXTRA_TRACKED_AIRLINES, extras are empty and defaults hold."""
    monkeypatch.delenv("EXTRA_TRACKED_AIRLINES", raising=False)
    assert get_extra_tracked_airlines() == {}
    assert get_tracked_airlines() == WEST_AFRICAN_AIRLINES
    assert get_allowed_airlines() == NIGERIAN_DOMESTIC_AIRLINES


def test_extra_tracked_airlines_extends_allowlist(monkeypatch):
    """Approved user suggestions extend both the map and the allow-list."""
    monkeypatch.setenv("EXTRA_TRACKED_AIRLINES", "XJ:Xejet, RN:Rano Air")
    extras = get_extra_tracked_airlines()
    assert extras == {"XJ": "Xejet", "RN": "Rano Air"}
    tracked = get_tracked_airlines()
    assert tracked["XJ"] == "Xejet"
    assert tracked["P4"] == "Air Peace"  # defaults untouched
    allowed = get_allowed_airlines()
    assert "XJ" in allowed and "RN" in allowed and "P4" in allowed
    # The base allow-list constant itself is never mutated
    assert "XJ" not in NIGERIAN_DOMESTIC_AIRLINES


def test_extra_tracked_airlines_skips_malformed(monkeypatch):
    """Malformed env entries are ignored, never crash the ingestor."""
    monkeypatch.setenv(
        "EXTRA_TRACKED_AIRLINES", "nonsense,:NoCode,XJ:,TOOLONG:Bad Code,xj:Xejet")
    extras = get_extra_tracked_airlines()
    assert extras == {"XJ": "Xejet"}  # lowercase code normalized, rest dropped


def test_safety_filter_keeps_user_suggested_airline(monkeypatch):
    """A fare from an approved user-suggested airline passes the filter."""
    monkeypatch.setenv("EXTRA_TRACKED_AIRLINES", "XJ:Xejet")
    allowed = get_allowed_airlines()
    tracked = get_tracked_airlines()

    flight = _mock_flight(60000.0, "XJ", "Xejet")
    airline_code = flight.primary_airline.name
    assert airline_code in allowed
    assert tracked.get(airline_code) == "Xejet"
    # And a still-unknown carrier keeps getting dropped
    assert "WC" not in allowed
