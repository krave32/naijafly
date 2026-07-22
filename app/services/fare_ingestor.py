"""Fare ingestion - explicit swap-in interface.

To go live for a carrier, implement FareIngestor.fetch_fares() and register it
in INGESTOR_REGISTRY. Everything downstream (price history, drop detection,
WhatsApp pushes) is real and unchanged.

CARRIER DATA STATUS (updated with Google Flights integration):
  - Air Peace (P4)  : Google Flights indexes their fares. LIVE via GoogleFlightsIngestor.
                      Amadeus GDS does NOT cover them.
  - Dana Air (9J)   : Google Flights may index limited fares (intermittent ops). LIVE via GoogleFlightsIngestor.
  - Ibom Air (QI)   : Google Flights may index limited fares.              LIVE via GoogleFlightsIngestor.
  - Arik Air (W3)   : Google Flights indexes their fares.                   LIVE via GoogleFlightsIngestor.
  - Africa World Airlines (AWA, Ghana, AW): Google Flights limited coverage. LIVE via GoogleFlightsIngestor.
  - United Nigeria Airlines (UN)           : Google Flights may index.      LIVE via GoogleFlightsIngestor.
  - Enugu Air (Q9)  : Google Flights limited coverage.                      LIVE via GoogleFlightsIngestor.
  - GDS (Amadeus/Travelport): Amadeus Self-Service API has a free tier. WIRED
    below as AmadeusFareIngestor. Covers GDS-connected carriers on international/
    regional routes but NOT the local carriers above.
  - Google Flights (fli): Reverse-engineered Google Flights API. Best coverage
    for Nigerian/West African domestic carriers since Google aggregates from
    airline websites and OTAs. WIRED below as GoogleFlightsIngestor.

Toggle which ingestor is active at runtime with the FARE_SOURCE env var
(mock|amadeus|google), read by get_active_ingestor(). No redeploy needed.
Use FARE_SOURCE=hybrid to combine Google Flights + Amadeus for maximum coverage.
"""
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List

import requests

logger = logging.getLogger("naijafly.fare_ingestor")


class FareIngestor(ABC):
    """Swap-in point: implement fetch_fares and register below."""

    @abstractmethod
    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        """Return list of {price, currency, source, flight_date} dicts."""


class MockFareIngestor(FareIngestor):
    """Deterministic-ish mock for local carriers with no API access.

    Prices vary around a base per route so the price-drop detector has
    something realistic to chew on.
    """

    BASE_PRICES = {
        # Nigeria domestic - major routes
        ("LOS", "ABV"): (85000, "NGN"),   # Lagos -> Abuja
        ("ABV", "LOS"): (82000, "NGN"),   # Abuja -> Lagos
        ("LOS", "PHC"): (78000, "NGN"),   # Lagos -> Port Harcourt
        ("PHC", "LOS"): (75000, "NGN"),   # Port Harcourt -> Lagos
        ("LOS", "ENU"): (65000, "NGN"),   # Lagos -> Enugu
        ("ENU", "LOS"): (62000, "NGN"),   # Enugu -> Lagos
        ("LOS", "BNI"): (70000, "NGN"),   # Lagos -> Benin City (Binani)
        ("BNI", "LOS"): (68000, "NGN"),   # Benin City -> Lagos
        ("LOS", "KAN"): (92000, "NGN"),   # Lagos -> Kano
        ("KAN", "LOS"): (90000, "NGN"),   # Kano -> Lagos
        ("LOS", "CBQ"): (72000, "NGN"),   # Lagos -> Calabar
        ("ABV", "PHC"): (88000, "NGN"),   # Abuja -> Port Harcourt
        ("ABV", "ENU"): (55000, "NGN"),   # Abuja -> Enugu
        ("ENU", "ABV"): (53000, "NGN"),   # Enugu -> Abuja
        ("ABV", "BNI"): (60000, "NGN"),   # Abuja -> Benin City
        # Nigeria <-> Ghana
        ("LOS", "ACC"): (185000, "NGN"),  # Lagos -> Accra
        ("ACC", "LOS"): (2100, "GHS"),    # Accra -> Lagos
        # Ghana domestic
        ("ACC", "KMS"): (900, "GHS"),     # Accra -> Kumasi
        ("KMS", "ACC"): (850, "GHS"),     # Kumasi -> Accra
        ("ACC", "TML"): (1100, "GHS"),    # Accra -> Tamale
        # West Africa regional
        ("LOS", "DKR"): (250000, "NGN"),  # Lagos -> Dakar
        ("ACC", "DKR"): (3500, "GHS"),    # Accra -> Dakar
        ("LOS", "ABJ"): (180000, "NGN"),  # Lagos -> Abidjan
        ("ACC", "ABJ"): (2800, "GHS"),    # Accra -> Abidjan
    }
    SOURCES = [
        "Air Peace", "Ibom Air", "Dana Air",
        "Africa World Airlines (Ghana)", "Arik Air", "Enugu Air",
        "United Nigeria Airlines", "ValueJet", "Green Africa Airways",
    ]

    def __init__(self, jitter: float = 0.15, seed: int = None):
        self.jitter = jitter
        self.rng = random.Random(seed)

    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        base, currency = self.BASE_PRICES.get(
            (origin.upper(), destination.upper()), (100000, "NGN"))
        fares = []
        for source in self.rng.sample(self.SOURCES, k=2):
            factor = 1 + self.rng.uniform(-self.jitter, self.jitter)
            fares.append({
                "price": round(base * factor, 2),
                "currency": currency,
                "source": source,
                "flight_date": date,
            })
        return fares


class ManualFeedIngestor(FareIngestor):
    """For fares phoned in / typed in by an ops person - reads a simple list.
    Real swap-in example: replace `self.feed` with a DB table or Google Sheet."""

    def __init__(self, feed: List[Dict] = None):
        self.feed = feed or []

    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        return [f for f in self.feed
                if f.get("origin") == origin and f.get("destination") == destination]


class AmadeusFareIngestor(FareIngestor):
    """Real GDS fares via the Amadeus Self-Service 'Flight Offers Search' API.

    Requires AMADEUS_API_KEY / AMADEUS_API_SECRET (free-tier self-service
    credentials from developers.amadeus.com). Uses the 'test' environment by
    default (test.api.amadeus.com) - that's what the free tier grants; set
    AMADEUS_HOSTNAME=production only once you have a paid production key.

    Amadeus airport codes are IATA codes, same as this app already uses
    (LOS, ACC, ABV, etc.) - no remapping needed.

    Known coverage gap (see module docstring): none of Air Peace, Dana Air,
    Ibom Air, Arik, or AWA are directly bookable via Amadeus's GDS content on
    most routes. Amadeus is genuinely useful for routes served by
    GDS-connected carriers (e.g. international legs, some regional codeshares)
    but every tracked LOCAL-carrier route will likely still come back empty -
    that's expected, not a bug. See fetch_fares()'s logging for exactly which
    routes returned data vs. came back empty on each run.
    """

    TOKEN_URL_TMPL = "https://{host}/v1/security/oauth2/token"
    OFFERS_URL_TMPL = "https://{host}/v2/shopping/flight-offers"

    def __init__(self, api_key: str = None, api_secret: str = None,
                 hostname: str = None, timeout: int = 15):
        self.api_key = api_key or os.getenv("AMADEUS_API_KEY")
        self.api_secret = api_secret or os.getenv("AMADEUS_API_SECRET")
        self.hostname = hostname or os.getenv("AMADEUS_HOSTNAME", "test.api.amadeus.com")
        self.timeout = timeout
        self._token = None
        self._token_expires_at = 0.0

    def _get_token(self) -> str:
        """Client-credentials OAuth2, cached until it expires."""
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "AMADEUS_API_KEY / AMADEUS_API_SECRET not set - cannot fetch a token.")
        resp = requests.post(
            self.TOKEN_URL_TMPL.format(host=self.hostname),
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + float(data.get("expires_in", 1799))
        return self._token

    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        origin, destination = origin.upper(), destination.upper()
        try:
            token = self._get_token()
        except Exception as e:
            logger.warning(
                "Amadeus auth failed for %s->%s: %s - falling back to no data this cycle.",
                origin, destination, e)
            return []

        try:
            resp = requests.get(
                self.OFFERS_URL_TMPL.format(host=self.hostname),
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDate": date.strftime("%Y-%m-%d"),
                    "adults": 1,
                    "max": 5,
                    "currencyCode": "NGN",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            offers = resp.json().get("data", [])
        except Exception as e:
            logger.info(
                "Amadeus returned no usable data for %s->%s: %s "
                "(expected for locally-only carriers not on GDS).",
                origin, destination, e)
            return []

        if not offers:
            logger.info(
                "Amadeus: 0 offers for %s->%s on %s - no GDS-connected carrier "
                "serves this route, or none available for that date.",
                origin, destination, date.strftime("%Y-%m-%d"))
            return []

        fares = []
        for offer in offers:
            try:
                price = float(offer["price"]["grandTotal"])
                currency = offer["price"]["currency"]
                carrier_code = offer["validatingAirlineCodes"][0] if offer.get(
                    "validatingAirlineCodes") else ""
                carrier_name = WEST_AFRICAN_AIRLINES.get(carrier_code, carrier_code)
                source = f"{carrier_name} ({carrier_code}) via Amadeus" if carrier_code else "Amadeus GDS"
                fares.append({
                    "price": price,
                    "currency": currency,
                    "source": source,
                    "flight_date": date,
                })
            except (KeyError, IndexError, ValueError, TypeError):
                continue  # skip malformed offer rather than fail the whole batch

        logger.info("Amadeus: %d real fare(s) fetched for %s->%s.",
                    len(fares), origin, destination)
        return fares


# -- Google Flights (fli) ingestor -----------------------------------------------

# IATA codes for Nigerian/West African airlines that Google Flights may index.
# Used by GoogleFlightsIngestor for source attribution and optional filtering.
WEST_AFRICAN_AIRLINES = {
    "P4": "Air Peace",
    "W3": "Arik Air",
    "QI": "Ibom Air",
    "9J": "Dana Air",
    "AW": "Africa World Airlines",
    "UN": "United Nigeria Airlines",
    "Q9": "Enugu Air",
    "VK": "ValueJet",
    "NK": "Green Africa Airways",
    "2P": "PAL Airlines (Nigeria)",
    # Regional carriers serving West Africa
    "ET": "Ethiopian Airlines",
    "KQ": "Kenya Airways",
    "AT": "Royal Air Maroc",
    "MS": "EgyptAir",
    "TU": "Tunisair",
    "HF": "Air Côte d'Ivoire",
    "SN": "Brussels Airlines",
    "AF": "Air France",
}

# Default currency mapping per destination airport country.
# Used when Google Flights returns prices in a different currency.
AIRPORT_CURRENCY = {
    # Nigeria
    "LOS": "NGN", "ABV": "NGN", "PHC": "NGN", "ENU": "NGN",
    "BNI": "NGN", "KAN": "NGN", "CBQ": "NGN", "QOW": "NGN",
    # Ghana
    "ACC": "GHS", "KMS": "GHS", "TML": "GHS",
    # Senegal
    "DKR": "XOF",
    # Côte d'Ivoire
    "ABJ": "XOF",
    # Sierra Leone
    "FNA": "SLL",
    # Burkina Faso
    "OUA": "XOF",
    # Gambia
    "BJL": "GMD",
    # Liberia
    "ROB": "LRD",
}


class GoogleFlightsIngestor(FareIngestor):
    """Real fares via Google Flights using the `fli` library (pip install flights).

    Google Flights aggregates fares from airline websites, OTAs, and GDS sources,
    giving the broadest coverage for West African carriers — including Air Peace,
    Arik Air, and others that are NOT on Amadeus GDS.

    This is the recommended production ingestor for Nigerian/West African domestic
    and regional routes. Falls back gracefully if `fli` is not installed or if
    Google rate-limits the request.

    Requires: pip install flights (the `fli` package on PyPI).
    No API key needed — uses reverse-engineered Google Flights internal API.

    Rate limiting: `fli` has built-in rate limiting. At typical poll intervals
    (5-15 min) across 15-20 routes, you should stay well within limits.
    """

    def __init__(self, currency: str = None, country: str = "NG",
                 max_results: int = 10, timeout: int = 30):
        self.default_currency = currency or os.getenv("GOOGLE_FLIGHTS_CURRENCY", "NGN")
        self.country = country
        self.max_results = max_results
        self.timeout = timeout
        self._fli_available = None  # lazy-check once

    def _check_fli(self) -> bool:
        """Check if the fli library is importable, cache the result."""
        if self._fli_available is not None:
            return self._fli_available
        try:
            import fli  # noqa: F401
            self._fli_available = True
        except ImportError:
            logger.warning(
                "fli library not installed. Run: pip install flights\n"
                "Google Flights ingestor will return no data until installed.")
            self._fli_available = False
        return self._fli_available

    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        if not self._check_fli():
            return []

        origin, destination = origin.upper(), destination.upper()
        # Determine the best currency for this route
        currency = AIRPORT_CURRENCY.get(destination, self.default_currency)

        try:
            from fli.models import (
                FlightSearchFilters, FlightSegment, PassengerInfo,
                SeatType, MaxStops, SortBy,
            )
            from fli.models.airport import Airport
            from fli.search import SearchFlights

            dep_airport = Airport[origin]
            arr_airport = Airport[destination]

            filters = FlightSearchFilters(
                passenger_info=PassengerInfo(adults=1),
                flight_segments=[
                    FlightSegment(
                        departure_airport=[[dep_airport, 0]],
                        arrival_airport=[[arr_airport, 0]],
                        travel_date=date.strftime("%Y-%m-%d"),
                    )
                ],
                seat_type=SeatType.ECONOMY,
                stops=MaxStops.ONE_STOP_OR_FEWER,
                sort_by=SortBy.CHEAPEST,
            )

            search = SearchFlights()
            results = search.search(
                filters,
                currency=currency,
                country=self.country,
            )

        except KeyError as e:
            logger.info(
                "Google Flights: airport %s not in fli database, skipping %s->%s.",
                e, origin, destination)
            return []
        except Exception as e:
            logger.warning(
                "Google Flights search failed for %s->%s on %s: %s",
                origin, destination, date.strftime("%Y-%m-%d"), e)
            return []

        if not results:
            logger.info(
                "Google Flights: 0 results for %s->%s on %s.",
                origin, destination, date.strftime("%Y-%m-%d"))
            return []

        fares = []
        for flight in results[:self.max_results]:
            try:
                price = float(flight.price) if hasattr(flight, 'price') else None
                if price is None or price <= 0:
                    continue

                # Extract airline info from flight legs
                airline_code = ""
                airline_name = "Unknown"
                if hasattr(flight, 'legs') and flight.legs:
                    leg = flight.legs[0]
                    if hasattr(leg, 'airline') and leg.airline:
                        airline_code = leg.airline.value if hasattr(leg.airline, 'value') else str(leg.airline)
                        airline_name = WEST_AFRICAN_AIRLINES.get(
                            airline_code, airline_code)

                source = f"{airline_name} via Google Flights"
                if airline_code:
                    source = f"{airline_name} ({airline_code}) via Google Flights"

                fares.append({
                    "price": price,
                    "currency": currency,
                    "source": source,
                    "flight_date": date,
                })
            except (AttributeError, TypeError, ValueError):
                continue  # skip malformed result

        logger.info(
            "Google Flights: %d fare(s) fetched for %s->%s on %s.",
            len(fares), origin, destination, date.strftime("%Y-%m-%d"))
        return fares


class HybridIngestor(FareIngestor):
    """Combines multiple ingestors for maximum coverage.

    Queries Google Flights first (broadest coverage for West African carriers),
    then Amadeus (GDS-connected international routes). Deduplicates by keeping
    all fares — the price-drop detection in FareService handles the rest.

    Activate with FARE_SOURCE=hybrid.
    """

    def __init__(self):
        self.ingestors = [
            GoogleFlightsIngestor(),
            AmadeusFareIngestor(),
        ]

    def fetch_fares(self, origin: str, destination: str, date: datetime) -> List[Dict]:
        all_fares = []
        for ingestor in self.ingestors:
            try:
                fares = ingestor.fetch_fares(origin, destination, date)
                all_fares.extend(fares)
            except Exception as e:
                logger.warning(
                    "Hybrid: %s failed for %s->%s: %s",
                    type(ingestor).__name__, origin, destination, e)
        logger.info(
            "Hybrid: %d total fare(s) for %s->%s from %d sources.",
            len(all_fares), origin, destination, len(self.ingestors))
        return all_fares


# Active ingestor per carrier/source. Swap MockFareIngestor for a real
# scraper class here and nothing else changes.
INGESTOR_REGISTRY = {
    "mock": MockFareIngestor,
    "amadeus": AmadeusFareIngestor,
    "google": GoogleFlightsIngestor,
    "hybrid": HybridIngestor,     # Google Flights + Amadeus combined
    "default": MockFareIngestor,  # back-compat alias for "mock"
}


def get_active_ingestor(name: str = None) -> FareIngestor:
    """Resolve which ingestor to use.

    Priority: explicit `name` argument > FARE_SOURCE env var > "mock".
    This is the single toggle point - nothing else in the codebase needs to
    know or care which source is active.

    Available sources:
      mock    - MockFareIngestor (deterministic test data, no API calls)
      amadeus - AmadeusFareIngestor (GDS fares, requires API credentials)
      google  - GoogleFlightsIngestor (Google Flights via fli, no key needed)
      hybrid  - HybridIngestor (Google Flights + Amadeus for max coverage)
    """
    if name is None:
        name = os.getenv("FARE_SOURCE", "mock")
    if name not in INGESTOR_REGISTRY:
        logger.warning("Unknown FARE_SOURCE=%r, falling back to mock.", name)
        name = "mock"
    return INGESTOR_REGISTRY[name]()
