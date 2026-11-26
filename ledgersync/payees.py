"""Payees a bookkeeper recognises by name: payment processors, whose payout is sales less their fees and refunds, and
consumer services that are usually personal spending. Kept here, in one place, so the reader's coding, the row checks
and the questions agree."""
from __future__ import annotations

import re
from typing import Optional

# Name as written in a payee or description, in lower case, against the name messages use.
PROCESSORS = {"stripe": "Stripe", "paypal": "PayPal", "square": "Square", "sumup": "SumUp", "zettle": "Zettle",
              "izettle": "Zettle", "shopify": "Shopify", "gocardless": "GoCardless", "amazon": "Amazon",
              "ebay": "eBay", "etsy": "Etsy"}
PERSONAL = {"netflix": "Netflix", "spotify": "Spotify", "disney plus": "Disney+", "disneyplus": "Disney+",
            "now tv": "NOW TV", "nowtv": "NOW TV", "audible": "Audible", "playstation": "PlayStation",
            "xbox": "Xbox", "nintendo": "Nintendo", "paramount plus": "Paramount+", "apple tv": "Apple TV",
            "prime video": "Prime Video", "youtube premium": "YouTube Premium", "crunchyroll": "Crunchyroll",
            "deezer": "Deezer", "tidal": "Tidal", "mubi": "MUBI", "britbox": "BritBox"}
# A film or TV streaming service named as Netflix is ("Streamflix", "Kidflix"): a word ending in "flix".
_FLIX = re.compile(r" ([a-z0-9]+flix) ")


# How a card statement words the money paid to the card from the bank.
_CARD_PAYMENT = re.compile(r"\b(payments?|thank ?you|direct debit|repayment|paid in full)\b")


def card_payment(*texts: Optional[str]) -> bool:
    """Whether a credit on a card statement is worded as a payment to the card ("PAYMENT RECEIVED - THANK YOU"),
    not a refund from a shop."""
    return any(_CARD_PAYMENT.search((text or "").lower()) for text in texts)


# How a bank line words money from a customer for work not yet invoiced.
_ON_ACCOUNT = re.compile(r"\b(on account|payment on a/?c|deposit|advance payment|in advance|retainer)\b")


def on_account(*texts: Optional[str]) -> bool:
    """Whether money in is worded as paid ahead of its invoice ("payment on account", "deposit")."""
    return any(_ON_ACCOUNT.search((text or "").lower()) for text in texts)


# How a bank line words a payment of part of a bill.
_PART_PAYMENT = re.compile(r"\b(deposit|part[- ]payment|instal?ments?|on account|payment on a/?c|balance (due|of|on)|"
                           r"final payment|stage payment)\b")


def part_payment(*texts: Optional[str]) -> bool:
    """Whether a payment's own words say it pays part of a bill ("deposit on van", "part payment on invoice 1001")."""
    return any(_PART_PAYMENT.search((text or "").lower()) for text in texts)


def _padded(text: Optional[str]) -> str:
    """The text's words in lower case, one space apart and padded with one each side: " netflix com "."""
    return f" {' '.join(re.findall(r'[a-z0-9]+', (text or '').lower()))} "


def _found(names: dict[str, str], *texts: Optional[str]) -> Optional[str]:
    for text in texts:
        padded = _padded(text)
        for written, name in names.items():
            if f" {written} " in padded:
                return name
    return None


def processor(*texts: Optional[str]) -> Optional[str]:
    """The payment processor the payee (or description) names, as messages name it; None for anyone else."""
    return _found(PROCESSORS, *texts)


# The owner's own bills, paid from the business account. A company may have a mortgage or council tax of its own,
# so those two are the owner's only for a business that is not a company.
OWNERS_TAX = {"self assessment": "Self Assessment tax", "hmrc sa": "Self Assessment tax"}
OWNERS_HOME = {"mortgage": "A mortgage", "council tax": "Council tax", "tv licence": "A TV licence",
               "tv licensing": "A TV licence"}


# A business whose trade is film, TV, music, streaming, gaming or other media: a streaming or gaming subscription may
# be for its work. By what the firm says it does, or by its SIC code (59: film, video, TV and music; 60: broadcasting;
# 90: creative arts and entertainment; 58210: publishing computer games).
_MEDIA_TRADE = re.compile(r"\b(film|films|tv|television|video|streaming|media|music|recording|record label|broadcast\w*|"
                          r"radio|podcast\w*|entertainment|content creat\w*|production company|post.production|"
                          r"animation|cinema|games|gaming|esports)\b", re.IGNORECASE)
_MEDIA_SIC = re.compile(r"^(59|60|90)\d{3}$|^58210$")


def media_business(nature_of_business: str = "", sic_code: str = "") -> bool:
    """Whether the business works in film, TV, music, streaming, gaming or other media."""
    return bool(_MEDIA_TRADE.search(nature_of_business or "")) or bool(_MEDIA_SIC.match((sic_code or "").strip()))


def consumer_service(*texts: Optional[str]) -> Optional[str]:
    """The streaming, music, audiobook or gaming service the payee (or description) names, as messages name it."""
    found = _found(PERSONAL, *texts)
    if found is None:
        flix = next((m.group(1) for text in texts if (m := _FLIX.search(_padded(text)))), None)
        found = flix.capitalize() if flix else None
    return found


def personal(*texts: Optional[str], business_type: Optional[str] = None, media: bool = False) -> Optional[str]:
    """What the payee (or description) names that is the owner's own spending, as messages name it: a consumer
    service (unless the business works in media, media=True: then it may be for its work); the owner's Self
    Assessment tax; and, for a business that is not a company, a mortgage or council tax. None for anything else."""
    names = dict(OWNERS_TAX)
    if business_type and business_type != "limited_company":
        names.update(OWNERS_HOME)
    return _found(names, *texts) or (None if media else consumer_service(*texts))
