"""The only way this package talks to the network.

  * HTTPS only, certificate and hostname checks always on (Python's default trust store).
  * Pinned hosts: the PayPal SANDBOX API and api.x.ai. The optional local explainer may use loopback only.
  * Redirects are refused (urllib would otherwise forward the Authorization header to the new host).
  * Timeouts on every call. Retries with backoff only when the caller says the call is safe to repeat
    (PayPal money calls are, because they carry a fixed PayPal-Request-Id: a repeat returns the first result).
  * Error text is scrubbed of secrets before it goes anywhere.
"""
from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .guard import scrub

PINNED_HOSTS = frozenset({"api-m.sandbox.paypal.com", "api.x.ai"})
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RESPONSE_BYTES = 2_000_000


class NetError(RuntimeError):
    """Network failure (timeout, refused, DNS, TLS). The request may or may not have reached the server."""


class BlockedTarget(ValueError):
    """A URL outside the pinned hosts, or not HTTPS."""


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NetError(f"redirect to another URL refused (HTTP {code})")


_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_tls_context()), _NoRedirect())


OPT_IN_HOSTS = frozenset({"api.twilio.com", "api.trychannel3.com"})   # only when a caller passes it AND the owner set their own key


def check_url(url: str, allow_loopback: bool = False, extra_host: str | None = None) -> str:
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if u.username or u.password:
        raise BlockedTarget("credentials in URL are not allowed")
    pinned = PINNED_HOSTS | ({extra_host} if extra_host in OPT_IN_HOSTS else set())
    if u.scheme == "https" and host in pinned and u.port in (None, 443):
        return url
    if allow_loopback and host in LOOPBACK and u.scheme in ("http", "https"):
        return url
    raise BlockedTarget(f"network target not allowed: {u.scheme}://{host}")


def is_loopback_url(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "").lower() in LOOPBACK


def request(method: str, url: str, headers: dict, body: bytes | None, timeout: float, *,
            retries: int = 0, backoff: float = 0.5, allow_loopback: bool = False, sleep=time.sleep,
            opener=None, extra_host: str | None = None) -> tuple:
    """Returns (status, lowercased headers, body bytes). HTTP error statuses are returned, not raised.
    Raises NetError if no HTTP answer arrived after all attempts."""
    check_url(url, allow_loopback=allow_loopback, extra_host=extra_host)
    op = opener or _OPENER
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with op.open(req, timeout=timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as e:
            status, hdrs, raw = e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read(MAX_RESPONSE_BYTES)
            if status in RETRY_STATUS and attempt < retries:
                attempt += 1
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            return status, hdrs, raw
        except NetError:
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException, ssl.SSLError, OSError) as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or isinstance(e, ssl.SSLCertVerificationError):
                raise NetError(scrub(f"TLS certificate check failed: {e}")) from None  # never retried, never bypassed
            if attempt < retries:
                attempt += 1
                sleep(backoff * (2 ** (attempt - 1)))
                continue
            raise NetError(scrub(f"{type(e).__name__}: {e}")[:300]) from None
