"""Tests for AmadeusFareIngestor and the FARE_SOURCE toggle.

All HTTP calls are mocked - these tests never hit the real Amadeus API.
"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.getcwd()))

from app.services.fare_ingestor import (
    AmadeusFareIngestor, MockFareIngestor, get_active_ingestor,
)


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


@patch("app.services.fare_ingestor.requests.get")
@patch("app.services.fare_ingestor.requests.post")
def test_amadeus_fetch_fares_success(mock_post, mock_get):
    mock_post.return_value = _mock_response(
        {"access_token": "fake-token", "expires_in": 1799})
    mock_get.return_value = _mock_response({
        "data": [
            {
                "price": {"grandTotal": "123456.78", "currency": "NGN"},
                "validatingAirlineCodes": ["KQ"],
            },
            {
                "price": {"grandTotal": "150000.00", "currency": "NGN"},
                "validatingAirlineCodes": ["ET"],
            },
        ]
    })

    ingestor = AmadeusFareIngestor(api_key="x", api_secret="y")
    fares = ingestor.fetch_fares("LOS", "ACC", datetime(2026, 8, 1))

    assert len(fares) == 2
    assert fares[0]["price"] == 123456.78
    assert fares[0]["currency"] == "NGN"
    assert "Amadeus" in fares[0]["source"]
    assert "KQ" in fares[0]["source"]
    # Token should be cached, not re-fetched on a second call this session
    ingestor.fetch_fares("LOS", "ACC", datetime(2026, 8, 1))
    assert mock_post.call_count == 1


@patch("app.services.fare_ingestor.requests.get")
@patch("app.services.fare_ingestor.requests.post")
def test_amadeus_no_offers_returns_empty_list(mock_post, mock_get):
    """Expected/normal for locally-only carriers not on GDS - not an error."""
    mock_post.return_value = _mock_response(
        {"access_token": "fake-token", "expires_in": 1799})
    mock_get.return_value = _mock_response({"data": []})

    ingestor = AmadeusFareIngestor(api_key="x", api_secret="y")
    fares = ingestor.fetch_fares("LOS", "PHC", datetime(2026, 8, 1))
    assert fares == []


@patch("app.services.fare_ingestor.requests.post")
def test_amadeus_auth_failure_returns_empty_list_not_exception(mock_post):
    mock_post.side_effect = Exception("network down")

    ingestor = AmadeusFareIngestor(api_key="x", api_secret="y")
    fares = ingestor.fetch_fares("LOS", "ACC", datetime(2026, 8, 1))
    assert fares == []  # must degrade gracefully, never crash the worker cycle


def test_amadeus_missing_credentials_returns_empty_list():
    ingestor = AmadeusFareIngestor(api_key=None, api_secret=None)
    fares = ingestor.fetch_fares("LOS", "ACC", datetime(2026, 8, 1))
    assert fares == []


@patch("app.services.fare_ingestor.requests.get")
@patch("app.services.fare_ingestor.requests.post")
def test_amadeus_skips_malformed_offer_without_failing_batch(mock_post, mock_get):
    mock_post.return_value = _mock_response(
        {"access_token": "fake-token", "expires_in": 1799})
    mock_get.return_value = _mock_response({
        "data": [
            {"price": {"grandTotal": "not-a-number", "currency": "NGN"}},  # malformed
            {"price": {"grandTotal": "99000.00", "currency": "NGN"},
             "validatingAirlineCodes": ["ET"]},  # valid
        ]
    })

    ingestor = AmadeusFareIngestor(api_key="x", api_secret="y")
    fares = ingestor.fetch_fares("LOS", "ACC", datetime(2026, 8, 1))
    assert len(fares) == 1
    assert fares[0]["price"] == 99000.00


def test_fare_source_toggle_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("FARE_SOURCE", raising=False)
    ingestor = get_active_ingestor()
    assert isinstance(ingestor, MockFareIngestor)


def test_fare_source_toggle_reads_env_var(monkeypatch):
    monkeypatch.setenv("FARE_SOURCE", "amadeus")
    ingestor = get_active_ingestor()
    assert isinstance(ingestor, AmadeusFareIngestor)


def test_fare_source_toggle_explicit_name_wins_over_env(monkeypatch):
    monkeypatch.setenv("FARE_SOURCE", "amadeus")
    ingestor = get_active_ingestor("mock")
    assert isinstance(ingestor, MockFareIngestor)


def test_fare_source_unknown_value_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("FARE_SOURCE", "not-a-real-source")
    ingestor = get_active_ingestor()
    assert isinstance(ingestor, MockFareIngestor)
