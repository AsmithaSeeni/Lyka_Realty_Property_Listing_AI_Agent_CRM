"""Format catalogue prices for written and spoken replies.

The property catalogue stores every price as a digit string using the
Indian lakh/crore grouping, for example ``65,00,000``. The digits are
the authoritative value; only the grouping differs from the
international style (``6,500,000``). The catalogue is a UAE property
dataset (every record is in Dubai, Abu Dhabi, Sharjah, Ajman or Umm
Al Quwain and every area is in sqft), so the prices are UAE dirhams.

This module never guesses a price: it only regroups and re-renders the
value that is already in the catalogue. The original string is always
preserved alongside the derived forms.

Offline tests: test_price_formatter.py
"""

import os
import re

# The catalogue currency. Every record in the dataset is a UAE
# property priced in dirhams.
CURRENCY = "AED"
CURRENCY_WORD = "dirhams"

# Approximate AED -> INR rate. This is a configured, clearly
# approximate reference rate, NOT a live FX feed: no rate API is
# connected to this project. Override with LYKA_AED_TO_INR. Any answer
# produced from it must say the rate is approximate.
AED_TO_INR_APPROXIMATE = float(
    os.environ.get("LYKA_AED_TO_INR", "23.0") or 23.0
)

_DIGITS = re.compile(r"^\d+$")


def parse_price(price_text):
    """Return the numeric value of a catalogue price, or None.

    Accepts "65,00,000", "6,500,000", "76000" and 6500000. Any
    grouping is accepted; the digits are what matter. A value that is
    not a plain digit string returns None so nothing is invented.
    """
    if price_text is None:
        return None
    if isinstance(price_text, bool):
        return None
    if isinstance(price_text, int):
        return price_text if price_text >= 0 else None
    if isinstance(price_text, float):
        return int(price_text) if price_text >= 0 else None
    text = str(price_text).strip().replace(",", "").replace(" ", "")
    if not text or not _DIGITS.match(text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def format_grouped(amount):
    """Return *amount* with international thousands grouping."""
    if amount is None:
        return ""
    return "{:,}".format(int(amount))


def format_millions(amount):
    """Return *amount* as a millions string, e.g. 6.5.

    Only exact values are returned: the string always converts back
    to the same number, so a price is never understated or
    overstated by the rounding. Returns None when the value does
    not divide cleanly into at most three decimal places.
    """
    if amount is None:
        return None
    amount = int(amount)
    whole, remainder = divmod(amount, 1000000)
    if remainder == 0:
        return str(whole)
    for decimals, divisor in ((1, 100000), (2, 10000), (3, 1000)):
        part = remainder // divisor
        if part * divisor == remainder:
            return "%d.%0*d" % (whole, decimals, part)
    return None


def price_display(price_text, currency=CURRENCY):
    """Exact, unambiguous price with currency, e.g. "AED 6,500,000".

    Returns "" when the value cannot be read, so a caller never
    displays a made-up price.
    """
    amount = parse_price(price_text)
    if amount is None:
        return ""
    return "%s %s" % (currency, format_grouped(amount))


def price_readable(price_text, currency=CURRENCY):
    """Short spoken-friendly price, e.g. "AED 6.5 million".

    Falls back to the exact grouped form whenever the millions
    wording would have to round the value, so the number the
    customer hears is never a different number.
    """
    amount = parse_price(price_text)
    if amount is None:
        return ""
    if amount >= 1000000:
        millions = format_millions(amount)
        if millions is not None:
            return "%s %s million" % (currency, millions)
    return "%s %s" % (currency, format_grouped(amount))


def price_lakh(price_text):
    """The price expressed in lakh (1 lakh = 100,000).

    Returns None when the value is below one lakh, where lakh wording
    would be misleading.
    """
    amount = parse_price(price_text)
    if amount is None or amount < 100000:
        return None
    return amount / 100000.0


def price_lakh_readable(price_text, currency=CURRENCY):
    """Lakh wording, e.g. "AED 65 lakh".

    Empty when the value does not convert to a clean lakh figure, so
    the customer is never told a misleading number.
    """
    amount = parse_price(price_text)
    if amount is None or amount < 100000:
        return ""
    whole, remainder = divmod(amount, 100000)
    tenth = remainder // 10000
    if tenth * 10000 != remainder:
        return ""
    if tenth == 0:
        return "%s %d lakh" % (currency, whole)
    return "%s %d.%d lakh" % (currency, whole, tenth)


def describe_price(price_text, currency=CURRENCY):
    """All price forms the agent may use, as one dict.

    ``price`` keeps the original catalogue string untouched.
    """
    amount = parse_price(price_text)
    return {
        "price": price_text,
        "price_numeric": amount,
        "price_display": price_display(price_text, currency),
        "price_readable": price_readable(price_text, currency),
        "price_lakh": price_lakh(price_text),
        "price_lakh_readable": price_lakh_readable(price_text, currency),
    }


def convert_to_inr(amount_aed, rate=AED_TO_INR_APPROXIMATE):
    """Approximate AED -> INR conversion.

    The rate is a configured reference value, not a live feed, so the
    result is marked approximate and the rate used is returned with it
    so the caller can disclose it.
    """
    amount = parse_price(amount_aed)
    if amount is None:
        return {
            "success": False,
            "message": "The amount could not be read, so no conversion was made.",
        }
    try:
        rate_value = float(rate)
    except (TypeError, ValueError):
        rate_value = AED_TO_INR_APPROXIMATE
    inr = amount * rate_value
    return {
        "success": True,
        "amount_aed": amount,
        "amount_inr": int(round(inr)),
        "amount_inr_display": "INR %s" % format_grouped(int(round(inr))),
        "amount_inr_lakh": round(inr / 100000.0, 2),
        "rate_used": rate_value,
        "rate_is_approximate": True,
        "note": (
            "The exchange rate used is a configured approximate "
            "reference rate, not a live market rate. Say that the "
            "figure is approximate and can change."
        ),
    }
