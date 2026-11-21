"""Failures are classified by exception type and HTTP status, never by text.

``as_vendor_error`` is the single place that maps a Yahoo client failure onto
the vendor-error taxonomy. The rule set it must obey:

    429                -> throttle            VendorRateLimitError
    401 / 403          -> credential rejected VendorAuthenticationError
    400 / 404          -> request refused     VendorRequestRejectedError
    5xx                -> transient service   VendorRateLimitError
    transport/timeout  -> unreachable         VendorRateLimitError
    other status       -> unclassified (raw exception preserved)
    JSON decode        -> unclassified (a bad body is not an absence)
    KeyError/TypeError -> unclassified (a bug is not an absence)

Both backends yfinance can use are covered, because their exception classes are
unrelated and both inherit ``OSError``.
"""
import pytest
import requests
from curl_cffi.requests import exceptions as curl_exc
from yfinance.exceptions import YFRateLimitError

import tradingagents.dataflows.stockstats_utils as su
from tradingagents.dataflows.errors import (
    VendorAuthenticationError,
    VendorRateLimitError,
    VendorRequestRejectedError,
)
from tradingagents.dataflows.stockstats_utils import as_vendor_error, is_transport_error


@pytest.mark.unit
class TestInstalledBackend:
    def test_the_classifier_follows_yfinance_s_actual_http_client(self):
        # yfinance 1.8 resolves ``requests`` to curl_cffi when available. If that
        # ever changes, this test states which backend the classifier must cover.
        assert su._yf_http.__name__ in ("curl_cffi.requests", "requests")

    def test_the_live_backend_s_error_classes_are_handled(self):
        # Not a simulation: the classes below are the ones yfinance will raise.
        assert issubclass(su._yf_http.exceptions.HTTPError, su._yf_http.exceptions.RequestException)
        assert issubclass(
            su._yf_http.exceptions.ConnectionError, su._yf_http.exceptions.RequestException
        )
        assert as_vendor_error(su._yf_http.exceptions.ConnectionError("x")) is not None

    def test_the_private_module_exists_at_the_declared_minimum(self):
        """``yfinance._http`` is private, so its support range is stated explicitly.

        The classifier imports ``yfinance._http.requests`` to learn which HTTP
        client yfinance actually uses. This test cannot download arbitrary
        historical wheels, so it does not prove the floor at runtime; it pins
        the fact the floor was checked (wheels inspected: 1.4.1, 1.6.0 and the
        installed version all ship ``yfinance/_http.py`` with a module-level
        ``requests``) and fails loudly if the declared floor changes, so the
        inspection must be repeated.
        """
        import re
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        match = re.search(r'"yfinance>=([0-9][^"]*)"', pyproject.read_text(encoding="utf-8"))
        assert match, "yfinance minimum version is not declared in pyproject.toml"
        inspected_floor = "1.4.1"
        assert match.group(1) == inspected_floor, (
            f"yfinance floor changed to {match.group(1)}: re-verify that this version "
            f"ships yfinance/_http.py exposing a module-level 'requests' before "
            f"trusting the classifier's import."
        )
        # The installed version must expose what the classifier imports.
        assert hasattr(su._yf_http, "exceptions")
        assert su._yf_http.__name__ in ("curl_cffi.requests", "requests")


TRANSPORT = [
    pytest.param(requests.Timeout("read timed out"), id="requests-timeout"),
    pytest.param(requests.ConnectionError("refused"), id="requests-connection"),
    pytest.param(requests.exceptions.SSLError("certificate"), id="requests-ssl"),
    pytest.param(requests.exceptions.ChunkedEncodingError("cut"), id="requests-chunked"),
    pytest.param(curl_exc.Timeout("read timed out"), id="curl-timeout"),
    pytest.param(curl_exc.ConnectionError("refused"), id="curl-connection"),
    pytest.param(curl_exc.RequestException("cURL error 7"), id="curl-request"),
    pytest.param(TimeoutError("socket timed out"), id="builtin-timeout"),
]


@pytest.mark.unit
class TestTransportAndThrottle:
    @pytest.mark.parametrize("exc", TRANSPORT)
    def test_transport_types_are_unavailable(self, exc):
        assert is_transport_error(exc)
        assert isinstance(as_vendor_error(exc), VendorRateLimitError)

    def test_yfinance_s_throttle_class_is_a_throttle_not_a_transport_error(self):
        # It says "too many requests", not "unreachable"; both map to the same
        # skip-this-vendor outcome, but only a real connection failure is
        # transport.
        exc = YFRateLimitError()
        assert not is_transport_error(exc)
        assert isinstance(as_vendor_error(exc), VendorRateLimitError)

    def test_a_bare_429_is_a_throttle(self, yahoo):
        for client in (requests, yahoo.curl_requests()):
            err = as_vendor_error(yahoo.status_error(client, 429))
            assert isinstance(err, VendorRateLimitError)
            assert "429" in str(err)

    def test_a_5xx_is_a_transient_service_error(self, yahoo):
        for client in (requests, yahoo.curl_requests()):
            for status in (500, 503):
                err = as_vendor_error(yahoo.status_error(client, status))
                assert isinstance(err, VendorRateLimitError), status


@pytest.mark.unit
class TestStatusCategories:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_statuses_are_credential_errors(self, yahoo, status):
        for client in (requests, yahoo.curl_requests()):
            err = as_vendor_error(yahoo.status_error(client, status))
            assert isinstance(err, VendorAuthenticationError), client.__name__
            assert not isinstance(err, (VendorRateLimitError, VendorRequestRejectedError))

    @pytest.mark.parametrize("status", [400, 404])
    def test_parameter_and_missing_resource_are_request_errors(self, yahoo, status):
        for client in (requests, yahoo.curl_requests()):
            err = as_vendor_error(yahoo.status_error(client, status))
            assert isinstance(err, VendorRequestRejectedError), client.__name__
            # Neither an outage to retry nor an absence to report.
            assert not isinstance(err, (VendorRateLimitError,))

    @pytest.mark.parametrize("status", [418, 451])
    def test_an_unrecognised_status_is_not_assumed_transient(self, yahoo, status):
        # Only 4xx codes that are neither auth, refusal nor throttle, plus any
        # status outside a known class, are left as raw errors. (302 is excluded:
        # raise_for_status() only raises for 4xx/5xx.)
        assert as_vendor_error(yahoo.status_error(requests, status)) is None


@pytest.mark.unit
class TestNotAnEvidenceOfAbsence:
    def test_json_decode_is_neither_transport_nor_classified(self):
        for exc in (
            requests.exceptions.JSONDecodeError("bad", "doc", 0),
            curl_exc.JSONDecodeError("bad"),
        ):
            assert not is_transport_error(exc)
            assert as_vendor_error(exc) is None

    def test_an_http_error_without_a_status_is_not_classified(self):
        assert as_vendor_error(requests.HTTPError("boom")) is None

    @pytest.mark.parametrize("exc", [KeyError("totalRevenue"), TypeError("bad"), ValueError("p")])
    def test_programming_errors_are_not_classified(self, exc):
        assert as_vendor_error(exc) is None

    def test_an_already_typed_error_is_returned_unchanged(self):
        exc = VendorAuthenticationError("x")
        assert as_vendor_error(exc) is exc


@pytest.mark.unit
class TestScrubbedStatusIsRecoverable:
    """``get_scrubbed`` detaches the response (it holds the keyed URL)."""

    def test_status_is_recovered_from_the_message_prefix(self):
        # Same shape get_scrubbed produces: rebuilt error, no response, keyed URL redacted.
        exc = requests.HTTPError("401 Client Error: Unauthorized for url: https://x/?k=***")
        assert as_vendor_error(exc) is not None
        assert isinstance(as_vendor_error(exc), VendorAuthenticationError)

    def test_a_scrubbed_body_error_is_not_mistaken_for_a_status(self):
        exc = requests.HTTPError("404 pages were not found while parsing")
        # Not a status prefix ("404 "), so it must not be read as HTTP 404.
        assert as_vendor_error(exc) is None
