"""v4 'price sanity' check (soft). A price far below what stores ask is a common fake-seller trick
("brand-new PS5 for $40"). It only ever HOLDS for your yes; it never blocks, sends or approves.

Pluggable: any object with market_prices(query, currency) -> list[float] works. The shipped one uses
Channel3 product search (https://docs.trychannel3.com/guides/search.md) with the OWNER'S OWN key from
the CHANNEL3_API_KEY environment variable. No key = the check does nothing (and no network call).
Only a few redacted product words are sent: no payee, emails, numbers, amounts or private terms."""
from __future__ import annotations

import json
import os
import re
import statistics

from . import net
from .guard import scrub
from .models import Finding, HOLD

ENV_KEY = "CHANNEL3_API_KEY"
HOST = "api.trychannel3.com"
URL = "https://api.trychannel3.com/v1/search"
RULE = "price_too_low"
TOO_LOW = 0.40          # under 40% of the typical new price
MIN_OFFERS = 3          # need at least 3 store prices to judge
MAX_WORDS = 8
BUY_HINT = re.compile(r"\b(buy|buying|bought|purchase|purchasing|order|ordering|for sale|seller|selling|listing|"
                      r"marketplace|brand[- ]new|used|deal)\b", re.I)
_DROP = re.compile(r"(https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\S*\d\S*)", re.I)
_STOP = {"a", "an", "the", "for", "from", "to", "of", "on", "in", "my", "your", "our", "with", "and", "or",
         "buy", "buying", "bought", "purchase", "purchasing", "order", "ordering", "sale", "seller", "selling",
         "listing", "marketplace", "deal", "payment", "pay", "paying", "please", "urgent", "this", "that", "is",
         "it", "via", "at", "by", "new", "brand", "used", "only", "today", "now"}


def product_query(description: str, payee: str = "", terms=()) -> str | None:
    """A few product words from the agent's text, or None if it does not look like a purchase."""
    text = str(description or "")
    if not BUY_HINT.search(text):
        return None
    if payee:
        text = text.replace(payee, " ")
    for t in terms or ():
        if t:
            text = re.sub(re.escape(str(t)), " ", text, flags=re.I)
    text = _DROP.sub(" ", text)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{1,24}", text) if w.lower() not in _STOP]
    words = words[:MAX_WORDS]
    return " ".join(words) if len(words) >= 1 else None


class Channel3Prices:
    """Owner's own Channel3 key, env only, never logged. HTTPS to api.trychannel3.com only."""
    name = "channel3"

    def __init__(self, env=None, sender=None):
        env = os.environ if env is None else env
        self._key = str(env.get(ENV_KEY, "")).strip()
        self._send = sender or net.request

    def __repr__(self):
        return f"Channel3Prices(ready={self.ready})"

    @property
    def ready(self) -> bool:
        return len(self._key) >= 8

    def market_prices(self, query: str, currency: str) -> list:
        body = json.dumps({"query": query, "limit": 10}).encode()
        try:
            code, _, raw = self._send("POST", URL, {"x-api-key": self._key, "Content-Type": "application/json",
                                                    "Accept": "application/json"}, body, 8, extra_host=HOST)
        except Exception as ex:
            raise RuntimeError(scrub(str(ex), extra=[self._key])[:160]) from None
        if code != 200:
            raise RuntimeError(f"Channel3 said HTTP {code}")
        data = json.loads(raw.decode("utf-8", "replace"))
        out = []
        for p in (data.get("products") or [])[:10]:
            for o in (p.get("offers") or [])[:10]:
                pr = o.get("price") or {}
                if (str(pr.get("currency", "")).upper() == currency.upper() and o.get("condition") in ("new", None)
                        and o.get("availability", "InStock") != "OutOfStock"):
                    try:
                        amt = float(pr.get("amount"))
                    except (TypeError, ValueError):
                        continue
                    if 0 < amt < 10_000_000:
                        out.append(amt)
        return out


def from_env(env=None):
    """The price source, or None (check off) when no CHANNEL3_API_KEY is set."""
    src = Channel3Prices(env)
    return src if src.ready else None


def judge(amount: str, currency: str, prices: list) -> Finding | None:
    """HOLD when the price is under 40% of the typical store price (needs 3+ store prices)."""
    if len(prices) < MIN_OFFERS:
        return None
    typical = statistics.median(prices)
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    if typical > 0 and amt < TOO_LOW * typical:
        return Finding(RULE, HOLD, f"This price is far below what stores ask (about {typical:,.0f} {currency}). "
                       "Very low prices are a common fake-seller trick. Check the seller before you pay.", 15)
    return None
