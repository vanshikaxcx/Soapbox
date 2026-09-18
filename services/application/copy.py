"""The exact words that must appear on the consent surfaces (WP-08, WP-09).

Copy lives here, in code, for one reason: these strings are load-bearing. The
simulation disclaimer is the difference between an honest demo and a misleading
one, and "we're confirming this payment" instead of "payment failed" is the
difference between a shopper who waits and a shopper who pays twice.

P1 owns the pixels. P1 does not own these sentences -- they are contract, and a
test asserts the ones that matter are present.
"""

from __future__ import annotations

from enum import StrEnum

from services.domain.money import Confidence

#: On every quote, approval and payment surface. SPEC section 1.
SIMULATION_DISCLAIMER = "Simulated checkout · no money moved · no retailer order placed."

#: Wherever fixture data is shown: comparison, quote and export.
FIXTURE_LABEL = "Demonstration data — fixture prices, not current retailer offers"

#: The only control permitted to call the approval endpoint. ``{amount}`` is the
#: exact total, formatted from integer paise at presentation time.
APPROVE_LABEL = "Approve simulated ₹{amount}"

#: The same control when the total is a ceiling rather than an exact price. The
#: words "up to" are load-bearing: without them a bound is read as a claim.
APPROVE_CEILING_LABEL = "Approve simulated up to ₹{amount}"


class PaymentCopy(StrEnum):
    """One line per payment state. ``unknown`` is never phrased as either outcome."""

    NOT_STARTED = "Ready to send"
    CLAIMED = "Sending your simulated payment"
    PENDING = "Payment in progress"
    #: Not "failed", which would be a lie, and not "succeeded", which would also
    #: be one. This sentence exists because the honest answer is neither.
    UNKNOWN = "We're confirming this payment"
    SUCCEEDED = "Payment confirmed"
    FAILED = "Payment did not go through"


class OrderCopy(StrEnum):
    NOT_CREATED = "No order yet"
    PENDING = "Creating your order"
    UNKNOWN = "We're checking whether an order exists"
    CONFIRMED = "Order confirmed"
    FAILED = "Order could not be created"


class BlockedCopy(StrEnum):
    EXPOSURE = "We're still confirming your last payment"
    QUOTE_EXPIRED = "This quote expired"
    PREPARATION_STALE = "These prices are no longer current"
    UNKNOWN_FEE = "We couldn't confirm the {charge} for this basket"
    UNPRICED_LINE = "We couldn't confirm the price for {item}"
    PACK_CHANGED = "The pack size changed at the merchant"
    CANCELLED = "Cancelled. Nothing was sent."
    PAID_NO_ORDER = "Paid, but we can't find an order"


#: A job failing says nothing about money. It gets its own wording so it cannot
#: be mistaken for a payment outcome on screen.
JOB_FAILED = "Something went wrong on our side. Your payment is unaffected."


def approve_label(total_paise: int, confidence: Confidence) -> str:
    """Render the approval control's label from integer paise.

    Formatting happens here, at the edge, and nowhere else: the domain never
    holds a decimal amount.

    ``confidence`` is required, not defaulted. A default would mean a caller who
    forgets it silently ships the un-hedged wording on an estimated total, which
    is the one mistake this function exists to prevent; forgetting it should be a
    TypeError at the call site instead.
    """
    rupees, paise = divmod(total_paise, 100)
    amount = f"{rupees}.{paise:02d}"
    if confidence is Confidence.UNKNOWN:
        # Unreachable through a quote -- can_build_quote refuses UNKNOWN before a
        # quote exists -- but a wrong label here would be a lie about money, so
        # this refuses rather than falling through to either wording.
        raise ValueError("an unknown total has no ceiling and cannot be approved")
    if confidence is Confidence.ESTIMATED:
        return APPROVE_CEILING_LABEL.format(amount=amount)
    return APPROVE_LABEL.format(amount=amount)


def lower_bound_label(floor_paise: int) -> str:
    """What to show when the total is unknown. Never a total, never zero.

    Takes ``Totals.floor``, not ``known_subtotal``. WP-02-A1 declassified
    ``known_subtotal`` as a bound: it counts estimated charges at their *upper*
    bound, so rendering "At least X" from it can promise a minimum the basket
    then falls below. ``floor`` sums verified amounts alone and is the only
    figure this sentence is true of.
    """
    rupees, paise = divmod(floor_paise, 100)
    return f"At least ₹{rupees}.{paise:02d}"


__all__ = [
    "APPROVE_LABEL",
    "FIXTURE_LABEL",
    "JOB_FAILED",
    "SIMULATION_DISCLAIMER",
    "BlockedCopy",
    "OrderCopy",
    "PaymentCopy",
    "approve_label",
    "APPROVE_CEILING_LABEL",
    "lower_bound_label",
]
