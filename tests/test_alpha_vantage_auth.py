"""A vendor that rejects the supplied key must say so, offline.

Covers the real request path, not a stub: ``_make_api_request`` builds the
parameters (including the key), calls ``get_scrubbed`` -- which performs the
request, raises for the status, and rebuilds the error without the response
(that object holds the keyed URL) -- and classifies the status it can still read.

The check has two halves: the typed error is right, and the key never appears in
the error, its chain, or its ``response`` (there is none).
"""
import pytest
import requests

import tradingagents.dataflows.alpha_vantage_common as av
from tradingagents.dataflows.errors import (
    VendorAuthenticationError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)

SECRET = "SECRETKEY0123456789"


class _Response:
    def __init__(self, status, url):
        self.status_code = status
        self.url = url
        self.text = ""

    def raise_for_status(self):
        if self.status_code < 400:
            return
        err = requests.HTTPError(
            f"{self.status_code} Client Error for url: {self.url}", response=self
        )
        raise err


def _fake_get(status, seen):
    def _get(url, params=None, timeout=None):
        seen.append(url + "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()))
        return _Response(status, f"{url}?apikey={SECRET}")

    return _get


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", SECRET)


@pytest.mark.unit
@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_raises_authentication_error(monkeypatch, configured, status):
    seen = []
    monkeypatch.setattr(av, "get_scrubbed", av.get_scrubbed)  # keep the real helper
    monkeypatch.setattr(requests, "get", _fake_get(status, seen))

    with pytest.raises(VendorAuthenticationError) as ctx:
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})

    assert not isinstance(ctx.value, (VendorNotConfiguredError, VendorRateLimitError))
    assert "API key" in str(ctx.value)
    assert SECRET not in str(ctx.value)
    assert SECRET not in repr(ctx.value)
    # Nothing in the chain re-attaches the keyed URL.
    cause = ctx.value.__cause__
    assert cause is None or SECRET not in str(cause)
    assert getattr(ctx.value, "response", None) is None
    # The request itself did carry the key (so this is the real path).
    assert any(SECRET in url for url in seen)


@pytest.mark.unit
def test_the_status_survives_scrubbing(monkeypatch, configured):
    # get_scrubbed rebuilds the error; the status must still be readable.
    def fake_get(url, params=None, timeout=None):
        return _Response(403, f"{url}?apikey={SECRET}")

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(requests.HTTPError) as ctx:
        av.get_scrubbed(av.API_BASE_URL, params={}, timeout=1, secret=SECRET)
    exc = ctx.value
    assert exc.response is not None and exc.response.status_code == 403
    assert SECRET not in str(exc)
    assert SECRET not in str(exc.response.__dict__)


@pytest.mark.unit
def test_a_429_is_still_a_throttle(monkeypatch, configured):
    monkeypatch.setattr(requests, "get", _fake_get(429, []))
    with pytest.raises(VendorRateLimitError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})


@pytest.mark.unit
def test_another_status_keeps_its_own_type(monkeypatch, configured):
    # 400 is not proven transient and not an absence: the HTTPError propagates.
    monkeypatch.setattr(requests, "get", _fake_get(400, []))
    with pytest.raises(requests.HTTPError) as ctx:
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    assert not isinstance(ctx.value, (VendorRateLimitError, VendorAuthenticationError))
    assert SECRET not in str(ctx.value)


@pytest.mark.unit
def test_a_missing_key_is_still_not_configured(monkeypatch):
    # The autouse fixture supplies a placeholder; remove it for this case.
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    with pytest.raises(VendorNotConfiguredError):
        av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
