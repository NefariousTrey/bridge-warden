"""v4 Market price column for the History grid (AG Grid). Made by @Nefarious_Trey, with Grok.
Copyright 2026 Trey (@Nefarious_Trey). Licensed under Apache-2.0 like the rest of the code.

What it does: for each buy, payment or refund it finds a "market price" for the item, works out how far the
amount is from it (difference %), and gives a ring colour so an overpriced buy or a too-good-to-be-true deal
stands out. It only ever WARNS on the History page. It never blocks, sends, approves or changes anything.

Where prices come from (free only, nothing is bought):
  * "example" (default): data/market_prices.example.json. Made-up demo prices, always labelled EXAMPLE.
    Swap the file (same shape) for a real source later.
  * "channel3" (off by default; set BW_MARKET_PRICES=channel3): reuses the typical store price that the
    Channel3 price check (price_check.py, the owner's own free-tier key) already wrote into the signed history
    when the payment was checked. No new network call is made here. Rows without one fall back to examples.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ENV_FLAG = "BW_MARKET_PRICES"
SOURCES = ("example", "channel3")
EXAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "market_prices.example.json"

# Ratio = amount / market price. Buys and payments:
TOO_LOW_RED = 0.40      # under 40% of usual: classic fake-seller bait (same line as price_check.TOO_LOW)
LOW_YELLOW = 0.70       # under 70%: unusually cheap, check the seller
HIGH_YELLOW = 1.25      # over 125%: paying more than usual
HIGH_RED = 2.00         # double or more: overpriced
# Refunds: a refund bigger than the item's usual price is odd.
REFUND_YELLOW = 1.10
REFUND_RED = 1.50

RING = {"green": 0, "yellow": 1, "red": 2}
SIDE = {"create_order": "Buy", "payout": "Pay", "refund": "Refund"}


def source_from_env(env=None) -> str:
    env = os.environ if env is None else env
    s = str(env.get(ENV_FLAG, "example")).strip().lower()
    return s if s in SOURCES else "example"


def load_examples(path: Path | None = None) -> list:
    """The example list. A broken or missing file just means "no market price" (never a crash)."""
    try:
        data = json.loads(Path(path or EXAMPLE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in data.get("items") or []:
        try:
            price = float(it["example_price"])
            kws = [str(k).lower() for k in it.get("keywords") or [] if str(k).strip()]
            name = str(it["name"])[:60]
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and kws:
            out.append({"name": name, "keywords": kws, "price": price})
    return out


def match(text: str, items: list) -> dict | None:
    """First item whose keyword appears as whole words in the text (longest keyword wins)."""
    low = " " + re.sub(r"[^a-z0-9-]+", " ", str(text or "").lower()) + " "
    best, best_len = None, 0
    for it in items:
        for k in it["keywords"]:
            if f" {k} " in low and len(k) > best_len:
                best, best_len = it, len(k)
    return best


def diff_pct(amount, market) -> float | None:
    """How far the amount is from the market price, in percent (+ = paid more). None if unknown."""
    try:
        a, m = float(amount), float(market)
    except (TypeError, ValueError):
        return None
    if m <= 0 or a < 0:
        return None
    return round((a - m) / m * 100.0, 1)


def price_flag(action: str, pct: float | None) -> tuple:
    """(ring colour or None, short plain words). None colour = no market price to compare."""
    if pct is None:
        return None, "No market price to compare."
    r = 1 + pct / 100.0
    if action == "refund":
        if r > REFUND_RED:
            return "red", "Refund is far over the item's usual price."
        if r > REFUND_YELLOW:
            return "yellow", "Refund is over the item's usual price."
        return "green", "Refund fits the item's usual price."
    if r < TOO_LOW_RED:
        return "red", "Too good to be true. Far under the usual price."
    if r < LOW_YELLOW:
        return "yellow", "Well under the usual price. Check the seller."
    if r >= HIGH_RED:
        return "red", "Overpriced. About double the usual price or more."
    if r > HIGH_YELLOW:
        return "yellow", "Over the usual price."
    return "green", "Near the usual price."


def worst(*rings) -> str:
    rs = [x for x in rings if x in RING]
    return max(rs, key=RING.get) if rs else "yellow"


def recorded_typicals(records: list) -> dict:
    """action_id -> typical store price the Channel3 check wrote in the signed history (if any)."""
    out = {}
    for r in records:
        if r.get("event") == "price_check":
            t = (r.get("result") or {}).get("typical")
            if isinstance(t, (int, float)) and t > 0:
                out[r.get("action_id")] = float(t)
    return out


def for_move(m: dict, items: list, recorded: dict, source: str) -> dict:
    """Market fields for one money move (a row from dashboard.moves())."""
    act = m.get("action") or ""
    hit = match(m.get("description", ""), items)
    market, src, name = None, None, hit["name"] if hit else None
    if source == "channel3" and m.get("action_id") in recorded:
        market, src = recorded[m["action_id"]], "channel3"
    elif hit and (m.get("currency") or "USD") == "USD":
        market, src = hit["price"], "example"
    pct = diff_pct(m.get("amount"), market) if market is not None else None
    ring, words = price_flag(act, pct)
    return {"side": SIDE.get(act, act), "item_match": name, "market": market, "market_source": src,
            "diff_pct": pct, "price_ring": ring, "price_words": words}
