import asyncio
import uuid
from typing import Any

import httpx

from ._json import error_envelope

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

# One shared connection pool for the process lifetime. No credentials are
# ever stored on it — client_id/client_secret/customer_number/country_code
# are passed per-call, so this is safe to share across tenants/requests (see
# server.py's contextvar-based credential isolation, which is what actually
# keeps tenants apart).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    return _http_client


# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def _classify(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    return "invalid_argument", False


class IngramMicroError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Ingram Micro API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = _classify(self.status_code)
        return error_envelope(code, self.message, retryable)


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2**attempt, _MAX_BACKOFF_SECONDS)


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
            if isinstance(detail, dict):
                # Ingram's error shape varies by layer: the OAuth/gateway
                # layer uses {"fault": {"faultstring": ...}}, the resellers
                # API itself uses {"message": ...}. Check both.
                fault = detail.get("fault")
                if isinstance(fault, dict) and fault.get("faultstring"):
                    msg = fault["faultstring"]
                else:
                    msg = detail.get("message") or str(detail)
            else:
                msg = str(detail)
        except ValueError:
            msg = resp.text
        raise IngramMicroError(resp.status_code, msg)


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict | None = None,
    json_body: Any = None,
) -> httpx.Response:
    """Issue one HTTP request against the shared connection pool, with
    limited retry + exponential backoff on 429/5xx and network-level
    errors (honoring Retry-After when the upstream sends one). Used for
    both the OAuth token exchange and the actual resellers API calls, so a
    transient blip on either leg gets the same treatment.
    """
    client = _get_http_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
        except httpx.RequestError as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                continue
            raise IngramMicroError(0, f"{e or type(e).__name__} (url={url})") from e

        if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
            await asyncio.sleep(_retry_delay(resp, attempt))
            continue
        return resp

    # Unreachable in practice (loop always returns or raises above), but
    # keeps type checkers happy and guards against future edits.
    if last_exc:
        raise IngramMicroError(0, f"{last_exc}") from last_exc
    raise IngramMicroError(0, "request failed with no response")


class IngramMicroClient:
    """Async httpx client wrapping the Ingram Micro Reseller API (Orders /
    Quote-to-Order surface), verified against Ingram Micro's own published
    OpenAPI spec (github.com/ingrammicro-xvantage/xi-sdk-openapispec,
    checked 2026-09-01).

    Auth: OAuth2 client_credentials grant, but via `GET /oauth/oauth20/token`
    with client_id/client_secret as QUERY parameters (not the more common
    Basic-Auth-header form) — this is Ingram's own documented shape, not a
    guess. The token is short-lived; since this is a stateless multi-tenant
    service, it deliberately re-authenticates on every call rather than
    caching (same "re-login every call" pattern as `cisco-umbrella-mcp`/
    `covedataprotection-mcp`/`webroot-mcp`).

    Every real API call additionally requires three business-context
    headers Ingram calls out as mandatory on Orders/Q2O endpoints —
    IM-CustomerNumber, IM-CountryCode, IM-CorrelationID — plus an optional
    IM-SenderID. IM-CorrelationID must be unique per transaction per
    Ingram's own docs, so this client generates a fresh UUID for every
    call rather than exposing it as a tool parameter (an agent has no way
    to know it needs to be unique-per-call, and getting it wrong is not a
    meaningful choice for the agent to make).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        customer_number: str,
        country_code: str,
        sender_id: str,
        base_url: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._customer_number = customer_number
        self._country_code = country_code
        self._sender_id = sender_id
        self._base_url = base_url.rstrip("/")

    async def _login(self) -> str:
        resp = await _request_with_retry(
            "GET",
            f"{self._base_url}/oauth/oauth20/token",
            headers={"Accept": "application/json"},
            params={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        _raise_for_status(resp)
        return resp.json()["access_token"]

    def _business_headers(self, token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "IM-CustomerNumber": self._customer_number,
            "IM-CountryCode": self._country_code,
            # Unique per transaction, per Ingram's own requirement — never
            # reused across calls or retries of the same logical call.
            "IM-CorrelationID": str(uuid.uuid4()),
        }
        if self._sender_id:
            headers["IM-SenderID"] = self._sender_id
        return headers

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "GET",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            params=self._clean_params(params),
        )
        return self._handle(resp)

    async def post(self, path: str, json_body: Any = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "POST",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            json_body=json_body,
        )
        return self._handle(resp)

    async def put(self, path: str, params: dict | None = None, json_body: Any = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "PUT",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            params=self._clean_params(params),
            json_body=json_body,
        )
        return self._handle(resp)

    async def delete(self, path: str, params: dict | None = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "DELETE",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            params=self._clean_params(params),
        )
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> Any:
        _raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
