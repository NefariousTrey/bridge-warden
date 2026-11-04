"""Money map (v6): where your money goes. READ-ONLY. It never moves money and never approves a hold.

The BW AG Grid agent (History page) uses this to:
  * sort spending into five groups by LOCAL rules (merchant words + PayPal fields): bills, subscriptions, gas,
    food, other. No AI decides a group.
  * flag money spikes: refund spikes, failed payments, unusual amounts.
  * find duplicate subscriptions (same service billed twice in a month, or two plans for one service) and
    subscriptions you may not use any more ("still use this?": we only see charges, never use).
Data comes from your Bridge Warden history (always) and, when the read-only money check read them, PayPal
transactions. In Dev mode / TEST MODE it is made-up SAMPLE data only.
Made by @Nefarious_Trey,
with Grok. Copyright 2026 Trey (@Nefarious_Trey). Apache-2.0.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

CATEGORIES = ("bills", "subscriptions", "gas", "food", "other")
CAT_LABEL = {"bills": "Bills", "subscriptions": "Subscriptions", "gas": "Gas", "food": "Food", "other": "Other"}
# BW colours (same palette as the History page). Each group also has a pattern + word, never colour alone.
CAT_COLOR = {"bills": "#1D4ED8", "subscriptions": "#7C3AED", "gas": "#B45309", "food": "#047857", "other": "#475569"}
SAMPLE_TAG = "SAMPLE"

# Local rules, checked in this order. Words are matched on whole-word boundaries, lower case.
# "gas bill" / "natural gas" are utility BILLS; "gas station" / "fuel" are GAS for a car.
RULES = (
    ("bills", ("gas bill", "gas company", "natural gas", "electric", "electricity", "power and light", "power & light",
               "energy", "water bill", "water dept", "utility", "utilities", "sewer", "trash", "internet", "broadband",
               "cable", "phone bill", "wireless bill", "mobile bill", "rent", "mortgage", "insurance", "loan payment",
               "car payment", "comcast", "xfinity", "verizon", "at&t", "t-mobile", "spectrum", "duke energy",
               "geico", "state farm", "progressive", "allstate")),
    ("gas", ("gas station", "fuel", "gasoline", "petrol", "diesel", "shell", "exxon", "exxonmobil", "mobil",
             "chevron", "bp", "sunoco", "speedway", "circle k", "marathon", "valero", "citgo", "wawa", "sheetz",
             "quiktrip", "racetrac", "pilot", "love's")),
    ("subscriptions", ("subscription", "streaming", "membership", "monthly plan", "premium", "netflix", "spotify",
                       "hulu", "disney+", "disney plus", "max", "youtube premium", "apple music", "icloud",
                       "apple one", "amazon prime", "prime video", "audible", "adobe", "microsoft 365",
                       "office 365", "xbox game pass", "playstation plus", "nintendo online", "patreon",
                       "dropbox", "google one", "chatgpt", "supergrok", "x premium", "news", "gym app")),
    ("food", ("restaurant", "pizza", "burger", "cafe", "coffee", "diner", "grill", "kitchen", "bakery", "taco",
              "sushi", "grocery", "groceries", "supermarket", "food", "doordash", "uber eats", "ubereats",
              "grubhub", "instacart", "starbucks", "mcdonald's", "mcdonalds", "chipotle", "subway", "wendy's",
              "chick-fil-a", "domino's", "kroger", "publix", "aldi", "whole foods", "trader joe's", "safeway",
              "costco", "food lion", "harris teeter")),
)
_RULE_RX = tuple((cat, re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])"))
                 for cat, words in RULES)
# PayPal Transaction Search event codes (transaction_info.transaction_event_code).
PAYPAL_SUB_CODES = {"T0002"}          # subscription payment
PAYPAL_REFUND_PREFIX = "T11"          # T11xx = reversals / refunds
FAILED_STATUS = {"D": "declined", "F": "failed", "V": "reversed"}
EMAILISH = re.compile(r"[^\s@]+@[^\s@]+")
DEFAULTS = {"still_use_months": 3, "unusual_times": 3.0, "unusual_min": 50, "refund_spike_count": 3,
            "keep_subscriptions": []}


def _dec(v):
    try:
        d = Decimal(str(v).strip())
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _when(s):
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def merchant_key(name: str) -> str:
    """Same service, same key: lower case, no plan words, no punctuation. 'Spotify Premium Family' -> 'spotify'."""
    s = re.sub(r"\(.*?\)", " ", str(name or "").lower())
    s = re.sub(r"\b(sample|inc|llc|ltd|co|corp|premium|family|plan|monthly|annual|subscription|membership|"
               r"individual|student|duo|basic|standard|plus|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s or "unknown"


def categorize(merchant: str, note: str = "", event_code: str = "") -> tuple:
    """(category, rule) by local rules only. rule says which word or field decided it, for the 'why' column."""
    if str(event_code or "").upper() in PAYPAL_SUB_CODES:
        return "subscriptions", "PayPal says subscription payment"
    text = f"{merchant or ''} {note or ''}".lower()
    for cat, rx in _RULE_RX:
        m = rx.search(text)
        if m:
            return cat, f'word "{m.group(1)}"'
    return "other", "no rule matched"


def display_merchant(name: str) -> str:
    """Never show or send a raw email as a merchant name."""
    n = " ".join(str(name or "").split())[:60]
    return "a person (email hidden)" if EMAILISH.search(n) or not n else n


def make_line(*, lid, at, merchant, amount, kind="paid", note="", event_code="", source="history", currency="USD"):
    amt = _dec(amount)
    when = _when(at)
    if amt is None or when is None:
        return None
    amt = abs(amt)
    cat, rule = categorize(merchant, note, event_code)
    return {"id": str(lid), "at": when.isoformat(), "month": when.strftime("%Y-%m"), "merchant": display_merchant(merchant),
            "key": merchant_key(merchant), "category": cat, "rule": rule, "amount": float(amt), "currency": currency,
            "kind": kind, "source": source, "flags": []}


def lines_from_history(records: list) -> list:
    """Sent, refunded and failed money moves from Bridge Warden's own signed history."""
    out = []
    for r in records:
        ev = r.get("event")
        if ev not in ("executed", "failed"):
            continue
        p = r.get("proposal") or {}
        kind = "failed" if ev == "failed" else ("refund" if p.get("action") == "refund" else "paid")
        ln = make_line(lid=r.get("action_id", r.get("seq")), at=r.get("clock_at") or r.get("at"),
                       merchant=p.get("payee", ""), amount=p.get("amount"), kind=kind,
                       note=p.get("description", ""), source="history", currency=p.get("currency", "USD"))
        if ln:
            out.append(ln)
    return out


def lines_from_paypal(txs: list) -> list:
    """PayPal Transaction Search rows (read-only GET). Uses only fields PayPal returns; no extra calls."""
    out = []
    for t in txs or []:
        ti = (t or {}).get("transaction_info") or {}
        amt = ti.get("transaction_amount") or {}
        code = str(ti.get("transaction_event_code", ""))
        status = str(ti.get("transaction_status", ""))
        pi = (t.get("payee_info") or t.get("payer_info") or {})
        name = ((pi.get("payer_name") or {}).get("alternate_full_name") or pi.get("business_name")
                or ti.get("transaction_subject") or ti.get("transaction_note") or "PayPal payment")
        kind = "failed" if status in FAILED_STATUS else ("refund" if code.startswith(PAYPAL_REFUND_PREFIX) else "paid")
        ln = make_line(lid=ti.get("transaction_id", ""), at=ti.get("transaction_initiation_date"), merchant=name,
                       amount=amt.get("value"), kind=kind, note=f"{ti.get('transaction_subject', '')} "
                       f"{ti.get('transaction_note', '')}", event_code=code, source="paypal",
                       currency=amt.get("currency_code", "USD"))
        if ln:
            out.append(ln)
    return out


# Made-up money for Dev mode / TEST MODE and the judge demo. Three months, every group, and the tricky cases:
# the same music service on two plans, a doubled charge, a big one-off, refunds piling up, and a failed bill.
SAMPLE_ROWS = (   # (days ago, merchant, amount, kind, note)
    (2, "SAMPLE Music streaming", "10.99", "paid", "monthly plan"),
    (3, "SAMPLE Music streaming (family plan)", "16.99", "paid", "monthly plan"),
    (32, "SAMPLE Music streaming", "10.99", "paid", "monthly plan"),
    (62, "SAMPLE Music streaming", "10.99", "paid", "monthly plan"),
    (5, "SAMPLE Video streaming", "15.49", "paid", "subscription"),
    (6, "SAMPLE Video streaming", "15.49", "paid", "subscription"),
    (36, "SAMPLE Video streaming", "15.49", "paid", "subscription"),
    (66, "SAMPLE Video streaming", "13.99", "paid", "subscription"),
    (9, "SAMPLE Gym app", "29.00", "paid", "membership"),
    (39, "SAMPLE Gym app", "29.00", "paid", "membership"),
    (69, "SAMPLE Gym app", "29.00", "paid", "membership"),
    (4, "SAMPLE City Power & Light", "118.40", "paid", "electric bill"),
    (34, "SAMPLE City Power & Light", "96.10", "paid", "electric bill"),
    (64, "SAMPLE City Power & Light", "88.75", "paid", "electric bill"),
    (7, "SAMPLE Home Internet", "65.00", "failed", "internet bill"),
    (8, "SAMPLE Home Internet", "65.00", "paid", "internet bill"),
    (38, "SAMPLE Home Internet", "65.00", "paid", "internet bill"),
    (12, "SAMPLE Car insurance", "142.00", "paid", "insurance"),
    (42, "SAMPLE Car insurance", "142.00", "paid", "insurance"),
    (1, "SAMPLE QuickFuel gas station", "48.20", "paid", "fuel"),
    (10, "SAMPLE QuickFuel gas station", "52.75", "paid", "fuel"),
    (20, "SAMPLE QuickFuel gas station", "45.10", "paid", "fuel"),
    (44, "SAMPLE QuickFuel gas station", "50.00", "paid", "fuel"),
    (58, "SAMPLE QuickFuel gas station", "47.35", "paid", "fuel"),
    (1, "SAMPLE Corner Pizza", "23.50", "paid", "restaurant"),
    (5, "SAMPLE Fresh Market groceries", "86.12", "paid", "groceries"),
    (13, "SAMPLE Fresh Market groceries", "92.40", "paid", "groceries"),
    (19, "SAMPLE Taco Truck", "14.25", "paid", "food"),
    (27, "SAMPLE Fresh Market groceries", "79.80", "paid", "groceries"),
    (47, "SAMPLE Fresh Market groceries", "88.00", "paid", "groceries"),
    (52, "SAMPLE Corner Pizza", "21.00", "paid", "restaurant"),
    (3, "SAMPLE Online shop", "389.00", "paid", "headphones"),
    (24, "SAMPLE Online shop", "35.00", "paid", "phone case"),
    (55, "SAMPLE Online shop", "42.00", "paid", "book"),
    (1, "SAMPLE Online shop", "35.00", "refund", "refund"),
    (2, "SAMPLE Online shop", "42.00", "refund", "refund"),
    (4, "SAMPLE Online shop", "19.99", "refund", "refund"),
    (50, "SAMPLE Online shop", "12.00", "refund", "refund"),
)


def sample_lines(now: datetime | None = None) -> list:
    now = now or datetime.now(timezone.utc)
    out = []
    for i, (days, merchant, amt, kind, note) in enumerate(SAMPLE_ROWS):
        ln = make_line(lid=f"sample-{i}", at=now - timedelta(days=days, hours=i % 7), merchant=merchant, amount=amt,
                       kind=kind, note=note, source="sample")
        out.append(ln)
    return out


def _flag(ln, kind, text):
    if kind not in [f["kind"] for f in ln["flags"]]:
        ln["flags"].append({"kind": kind, "text": text})


def analyze(lines: list, cfg: dict | None = None, now: datetime | None = None) -> dict:
    """Totals, charts and flags. Local rules only. Pure function (no I/O)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    now = now or datetime.now(timezone.utc)
    lines = [dict(x, flags=list(x.get("flags", []))) for x in lines if x]
    lines.sort(key=lambda x: x["at"], reverse=True)
    paid = [x for x in lines if x["kind"] == "paid"]
    flags = []

    # Subscriptions also by repeat: same merchant, similar amount, 2+ different months, not a bill.
    by_key = defaultdict(list)
    for x in paid:
        by_key[x["key"]].append(x)
    for key, items in by_key.items():
        months = {x["month"] for x in items}
        if len(months) >= 2 and all(x["category"] == "other" for x in items):
            amts = [x["amount"] for x in items]
            if max(amts) - min(amts) <= max(1.0, 0.1 * max(amts)):
                for x in items:
                    x["category"], x["rule"] = "subscriptions", "repeats every month"

    # 1. failed payments
    for x in lines:
        if x["kind"] == "failed":
            _flag(x, "failed", "This payment failed. It did not go through.")
            flags.append({"kind": "failed", "level": "look", "id": x["id"], "category": x["category"],
                          "text": f"A {CAT_LABEL[x['category']].lower()} payment to {x['merchant']} for "
                                  f"${x['amount']:,.2f} failed. Check your card or bank so it does not lapse."})

    # 2. refund spike: N+ refunds in the last 7 days, more than any earlier week.
    refunds = [x for x in lines if x["kind"] == "refund"]
    recent = [x for x in refunds if _when(x["at"]) >= now - timedelta(days=7)]
    older = [x for x in refunds if _when(x["at"]) < now - timedelta(days=7)]
    weeks = defaultdict(int)
    for x in older:
        weeks[(now - _when(x["at"])).days // 7] += 1
    if len(recent) >= int(cfg["refund_spike_count"]) and len(recent) > max(weeks.values(), default=0):
        for x in recent:
            _flag(x, "refund_spike", "Part of a burst of refunds this week.")
        flags.append({"kind": "refund_spike", "level": "look", "category": "other",
                      "text": f"{len(recent)} refunds in the last 7 days (${sum(x['amount'] for x in recent):,.2f}). "
                              "That is more than usual. Scammers sometimes fake refunds or 'overpay' you. "
                              "Check each one is real before you send anything back."})

    # 3. unusual amounts: 3x the usual for that group (or for everything, if the group is small).
    allamts = [x["amount"] for x in paid]
    for x in paid:
        same = [y["amount"] for y in paid if y["category"] == x["category"] and y is not x]
        base = same if len(same) >= 3 else [a for a in allamts if a is not x["amount"]]
        if len(base) < 3:
            continue
        med = statistics.median(base)
        if med > 0 and x["amount"] >= med * float(cfg["unusual_times"]) and x["amount"] >= float(cfg["unusual_min"]):
            _flag(x, "unusual", f"Much bigger than your usual (${med:,.2f}).")
            flags.append({"kind": "unusual", "level": "look", "id": x["id"], "category": x["category"],
                          "text": f"${x['amount']:,.2f} at {x['merchant']} is about {x['amount'] / med:.0f} times "
                                  f"your usual ${med:,.2f}. Worth a look."})

    # 4. duplicate subscriptions
    subs = [x for x in paid if x["category"] == "subscriptions"]
    family = defaultdict(list)
    for x in subs:
        family[x["key"]].append(x)
    for key, items in family.items():
        per_month = defaultdict(list)
        for x in items:
            per_month[x["month"]].append(x)
        doubled = [g for g in per_month.values() if len(g) >= 2]
        if doubled:
            g = doubled[0]
            for x in g:
                _flag(x, "duplicate", "Same service charged twice this month.")
            names = sorted({x["merchant"] for x in g})
            how = ("two plans for the same service" if len(names) > 1 else "charged twice in one month")
            flags.append({"kind": "duplicate", "level": "look", "category": "subscriptions", "key": key,
                          "text": f"{names[0]}: {how} (${sum(x['amount'] for x in g):,.2f}). You may be paying "
                                  "twice. Keep one, cancel the other at the service (Bridge Warden never cancels)."})

    # 5. still use this? (we only see charges, never use) and price went up
    keep = {merchant_key(k) for k in cfg.get("keep_subscriptions") or []}
    for key, items in family.items():
        months = sorted({x["month"] for x in items})
        if len(months) >= int(cfg["still_use_months"]) and key not in keep:
            total = sum(x["amount"] for x in items)
            flags.append({"kind": "still_use", "level": "info", "category": "subscriptions", "key": key,
                          "text": f"{items[0]['merchant']}: paid {len(months)} months in a row (${total:,.2f}). "
                                  "Still use it? Bridge Warden sees charges only, not use. If yes, add it to "
                                  "keep_subscriptions and this note goes away."})
        by_m = sorted(items, key=lambda x: x["at"])
        if len(by_m) >= 2 and by_m[-1]["amount"] > by_m[0]["amount"] + 0.5 and len({x["merchant"] for x in by_m}) == 1:
            flags.append({"kind": "price_up", "level": "info", "category": "subscriptions", "key": key,
                          "text": f"{by_m[-1]['merchant']} went up from ${by_m[0]['amount']:,.2f} to "
                                  f"${by_m[-1]['amount']:,.2f}."})

    totals = {c: 0.0 for c in CATEGORIES}
    months = sorted({x["month"] for x in paid})[-6:]
    by_month = {m: {c: 0.0 for c in CATEGORIES} for m in months}
    for x in paid:
        totals[x["category"]] += x["amount"]
        if x["month"] in by_month:
            by_month[x["month"]][x["category"]] += x["amount"]
    top = defaultdict(float)
    for x in paid:
        top[(x["merchant"], x["category"])] += x["amount"]
    order = {"look": 0, "info": 1}
    flags.sort(key=lambda f: order.get(f["level"], 2))
    return {"lines": lines, "flags": flags,
            "totals": {c: round(v, 2) for c, v in totals.items()}, "total": round(sum(totals.values()), 2),
            "refunds": round(sum(x["amount"] for x in refunds), 2), "failed": len([x for x in lines if x["kind"] == "failed"]),
            "by_month": {m: {c: round(v, 2) for c, v in d.items()} for m, d in by_month.items()},
            "top": [{"merchant": m, "category": c, "amount": round(a, 2)}
                    for (m, c), a in sorted(top.items(), key=lambda kv: -kv[1])[:8]],
            "sample": any(x["source"] == "sample" for x in lines)}


def redacted(report: dict) -> dict:
    """The ONLY money-map data that may go to an AI: groups, totals, flag kinds and counts. No merchant names,
    no emails, no ids, no single payments."""
    kinds = defaultdict(int)
    for f in report["flags"]:
        kinds[f["kind"]] += 1
    return {"totals_by_group": report["totals"], "total": report["total"], "refunds_total": report["refunds"],
            "failed_payments": report["failed"], "flag_counts": dict(kinds),
            "months": {m: d for m, d in report["by_month"].items()}}
