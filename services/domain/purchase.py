"""Preparation freshness, quote construction and attempt-creation rules (WP-02).

The two safety rules other packages depend on:

``may_create_attempt`` -- a second payment attempt is permitted only when the
previous one is definitively over. Pending, unknown and succeeded all block it:
pending and unknown because we might already have paid, succeeded because we
certainly have.

``can_build_quote`` -- a quote requires a bounded total. UNKNOWN blocks it,
because an unknown charge has no ceiling and there is no maximum to authorise.
ESTIMATED is permitted and approves as a ceiling: the charge is carried at its
upper bound, so the control reads "Approve simulated up to Rs X", which is a
true sentence about the basket (WP-02-A1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field, model_validator

from services.domain.errors import (
    AttemptBlockedByExposure,
    DiffNotAccepted,
    PreparationExpired,
    QuoteExpired,
    QuoteHashMismatch,
    QuoteNotConstructible,
)
from services.domain.ids import Digest, Id, Mode, Record, Timestamped
from services.domain.keys import diff_hash
from services.domain.keys import payment_key as build_payment_key
from services.domain.keys import payment_request_hash as build_payment_request_hash
from services.domain.keys import quote_hash as build_quote_hash
from services.domain.money import Charge, Confidence, Currency, Money, Totals, total_of, worst
from services.domain.transitions import (
    ApprovalState,
    ClaimState,
    DispatchState,
    OrderState,
    PaymentState,
    RefundState,
)


class ChangeKind(StrEnum):
    """What a re-check can find different from what the shopper was shown."""

    PRICE = "price"
    AVAILABILITY = "availability"
    PACK = "pack"
    FEE = "fee"
    DELIVERY = "delivery"


class Change(Record):
    """One difference, with both sides, so the UI never has to guess wording."""

    kind: ChangeKind
    target: str
    before: str
    after: str


class Diff(Record):
    """The exact change list a shopper is asked to accept, and its hash.

    Acceptance is by hash, so a shopper can only accept the list they were shown.
    An empty diff requires no acceptance at all.
    """

    changes: tuple[Change, ...] = ()

    @property
    def requires_acceptance(self) -> bool:
        return bool(self.changes)

    def hash(self) -> str:
        return diff_hash(list(self.changes))


def build_diff(changes: Sequence[Change]) -> Diff:
    return Diff(changes=tuple(changes))


#: Defaults from SPEC section 6. Both are parameters, both are checked against an
#: injected server clock, and both are always shown to the shopper.
PREPARATION_FRESHNESS_SECONDS = 120
QUOTE_LIFETIME_SECONDS = 120


class Preparation(Timestamped):
    """A re-check of the chosen basket, with the changes it found."""

    preparation_id: str
    purchase_id: str
    refreshed_at: datetime
    diff_hash: Digest
    change_count: int = Field(ge=0)
    accepted_diff_hash: Digest | None = None
    version: int = 1

    @property
    def requires_acceptance(self) -> bool:
        return self.change_count > 0

    @property
    def is_accepted(self) -> bool:
        return self.accepted_diff_hash == self.diff_hash


class QuoteWindow(Timestamped):
    """The lifetime of an immutable quote."""

    issued_at: datetime
    expires_at: datetime


class AttemptSnapshot(Record):
    """Just enough of an attempt to decide whether another one is permitted."""

    attempt_id: str
    dispatch: DispatchState
    payment: PaymentState


class PurchaseSnapshot(Record):
    active_attempt: AttemptSnapshot | None = None
    last_attempt: AttemptSnapshot | None = None


# -- freshness -------------------------------------------------------------


def is_fresh(
    preparation: Preparation,
    now: datetime,
    freshness_seconds: int = PREPARATION_FRESHNESS_SECONDS,
) -> bool:
    """Fresh strictly inside the window; exactly at the boundary is stale."""
    return now - preparation.refreshed_at < timedelta(seconds=freshness_seconds)


def is_quote_live(window: QuoteWindow, now: datetime) -> bool:
    """Live strictly before expiry; exactly at expiry is expired."""
    return now < window.expires_at


def quote_window(now: datetime, lifetime_seconds: int = QUOTE_LIFETIME_SECONDS) -> QuoteWindow:
    return QuoteWindow(issued_at=now, expires_at=now + timedelta(seconds=lifetime_seconds))


# -- quote construction ----------------------------------------------------


def can_build_quote(
    preparation: Preparation, totals: Totals, now: datetime
) -> None | PreparationExpired | DiffNotAccepted | QuoteNotConstructible:
    """Decide whether an exact quote may be built. None means yes.

    The anti-loop rule lives here: a fresh preparation whose diff has been
    accepted yields a quote *without another refresh*. Re-refreshing at this
    point is what turns recheck into an endless loop, because every refresh can
    produce a new diff to accept.
    """
    if not is_fresh(preparation, now):
        return PreparationExpired(preparation_id=preparation.preparation_id)

    if preparation.requires_acceptance and not preparation.is_accepted:
        # The taxonomy has a dedicated error for this; overloading
        # QuoteNotConstructible would make WP-08 switch on a reason string to
        # tell two genuinely different conditions apart.
        return DiffNotAccepted(preparation_id=preparation.preparation_id)

    if totals.confidence is Confidence.UNKNOWN:
        return QuoteNotConstructible(
            reason="unpriced_line" if totals.unpriced_lines else "unknown_charge",
            charge_kinds=tuple(str(k) for k in totals.unknown_charges),
        )

    if totals.estimated_lines:
        # A ceiling on a *fee* is expressible: the charge carries its own
        # confidence and the control says "up to". A ceiling on a *line* is not
        # -- QuoteLine.line_total is a plain Money, so the quote would show an
        # estimated item price as though it were exact, and total_confidence
        # (which reads the charges) would report the whole total as verified.
        # Refuse rather than render a ceiling as a price.
        return QuoteNotConstructible(reason="estimated_line", charge_kinds=())

    # An ESTIMATED total is approvable, as a ceiling (WP-02-A1 §5). Every
    # estimated charge is carried at its upper bound, so "up to X" is a true
    # statement about the basket and the control says exactly that. The live
    # merchants can never report a complete fee -- their fees only exist inside a
    # cart nobody may touch -- so refusing an estimate here refused every live
    # purchase outright rather than protecting anyone.
    #
    # UNKNOWN stays refused above: no ceiling exists, so there is no maximum to
    # authorise and nothing honest to put on the button.
    return None


def check_quote_live(quote_id: str, window: QuoteWindow, now: datetime) -> None | QuoteExpired:
    if not is_quote_live(window, now):
        return QuoteExpired(quote_id=quote_id)
    return None


# -- exposure --------------------------------------------------------------

#: Payment states that mean money may already have moved, or certainly has.
EXPOSED_PAYMENT_STATES = frozenset(
    {
        PaymentState.CLAIMED,
        PaymentState.PENDING,
        PaymentState.UNKNOWN,
        PaymentState.SUCCEEDED,
    }
)


def has_unresolved_exposure(attempt: AttemptSnapshot) -> bool:
    """True when a provider call happened and its outcome is not definitively over.

    ``succeeded`` counts as exposure for the purpose of blocking a *replacement*
    attempt: the purchase is paid, and a second attempt would be a second charge.
    """
    if attempt.dispatch is not DispatchState.STARTED:
        return False
    return attempt.payment in EXPOSED_PAYMENT_STATES


def may_create_attempt(purchase: PurchaseSnapshot) -> None | AttemptBlockedByExposure:
    """None means a new attempt is permitted.

    Permitted only when there is no active attempt and the previous one ended in
    a definitive failure, or was never sent at all.
    """
    if purchase.active_attempt is not None:
        active = purchase.active_attempt
        return AttemptBlockedByExposure(
            payment_state=str(active.payment), dispatch_state=str(active.dispatch)
        )

    previous = purchase.last_attempt
    if previous is None:
        return None

    if previous.dispatch is DispatchState.EXPIRED_UNSENT:
        return None  # no provider call was ever made
    if previous.payment is PaymentState.FAILED:
        return None  # definitively over

    return AttemptBlockedByExposure(
        payment_state=str(previous.payment), dispatch_state=str(previous.dispatch)
    )


# -- the commerce core -----------------------------------------------------
#
# These are the records WP-08 writes inside one transaction and WP-09 reads on
# every checkout attempt. They live here so there is exactly one shape for each,
# shared by the handler, the workflow, the simulator adapter and recovery.


class QuoteLine(Record):
    """One line of a quote, frozen at the moment consent was given."""

    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    quantity_base: int = Field(gt=0)
    dimension: str = Field(min_length=1, max_length=16)
    unit_price: Money
    line_total: Money
    substituted: bool = False


class CheckoutQuote(Timestamped):
    """An immutable, exactly-priced offer, bound to its hash.

    Immutable in the strongest sense available: frozen, and every term that was
    shown is bound into ``quote_hash``. A "new quote" is a new record with a
    higher ``quote_version``, never an edit of this one.
    """

    quote_id: Id
    purchase_id: Id
    owner_id: Id
    purchase_version: int = Field(ge=1)
    quote_version: int = Field(ge=1)
    demo_seller_id: str = Field(min_length=1, max_length=64)
    source_merchant_id: str = Field(min_length=1, max_length=64)
    mode: Mode
    lines: tuple[QuoteLine, ...] = Field(min_length=1)
    charges: tuple[Charge, ...] = ()
    total: Money
    currency: Currency = Currency.INR
    delivery: str = Field(min_length=1, max_length=120)
    issued_at: datetime
    expires_at: datetime
    quote_hash: Digest

    @property
    def total_confidence(self) -> Confidence:
        """Whether ``total`` is an exact price or a ceiling.

        Derived from the charges rather than stored, so it cannot contradict
        them. Reading the charges alone is only sound because ``can_build_quote``
        refuses a total carrying an unpriced *or* estimated line: a ``QuoteLine``
        holds a plain ``Money`` and has nowhere to record that it is a ceiling,
        so a quote's lines are exact by enforcement, not by assumption. A quote
        is never UNKNOWN for the same reason.
        """
        return worst([c.confidence for c in self.charges])

    @model_validator(mode="after")
    def _total_is_the_sum_of_its_parts(self) -> CheckoutQuote:
        parts = [line.line_total for line in self.lines]
        parts += [c.amount for c in self.charges if c.amount is not None]
        if total_of(parts) != self.total:
            raise ValueError("quote total does not equal the sum of its lines and charges")
        return self

    @model_validator(mode="after")
    def _every_charge_is_known(self) -> CheckoutQuote:
        """A quote cannot contain a fee we could not bound.

        UNKNOWN is refused: the control would have to name an amount that no
        charge supports. ESTIMATED is allowed and makes ``total`` a ceiling --
        the control then reads "Approve simulated up to Rs X", which is true
        because an estimated charge is carried at its upper bound (WP-02-A1).
        """
        for charge in self.charges:
            if charge.confidence is Confidence.UNKNOWN:
                raise ValueError(
                    f"quote carries an unknown {charge.kind} charge; "
                    "an unknown fee has no ceiling and cannot be quoted"
                )
        return self

    def recompute_hash(self) -> str:
        """Rebuild the hash from the stored terms, for tamper detection."""
        return build_quote_hash(
            owner_id=self.owner_id,
            purchase_id=self.purchase_id,
            purchase_version=self.purchase_version,
            quote_id=self.quote_id,
            quote_version=self.quote_version,
            seller_id=self.demo_seller_id,
            source_merchant_id=self.source_merchant_id,
            mode=self.mode,
            lines=self.lines,
            charges=self.charges,
            currency=self.currency,
            delivery=self.delivery,
            expires_at=self.expires_at,
        )

    def verify(self, submitted_hash: str) -> None | QuoteHashMismatch:
        """Check the stored terms against both the stored and submitted hashes.

        One check catches two different problems: a tampered client payload, and
        a stored record that no longer matches its own hash.
        """
        recomputed = self.recompute_hash()
        if recomputed != self.quote_hash:
            return QuoteHashMismatch(expected=recomputed, submitted=self.quote_hash)
        if submitted_hash != self.quote_hash:
            return QuoteHashMismatch(expected=self.quote_hash, submitted=submitted_hash)
        return None

    @property
    def window(self) -> QuoteWindow:
        return QuoteWindow(issued_at=self.issued_at, expires_at=self.expires_at)


class Approval(Record):
    """Consent to exact terms. One-shot, identified by what was consented to.

    ``approval_id`` is derived from the quote rather than minted per request, so
    two concurrent approvals of one quote produce the same approval and the same
    payment key -- which is what lets the uniqueness conditions catch a duplicate.
    """

    approval_id: Digest
    quote_id: Id
    quote_hash: Digest
    quote_version: int = Field(ge=1)
    purchase_version: int = Field(ge=1)
    owner_id: Id
    status: ApprovalState = ApprovalState.ISSUED
    consumed_attempt_id: Id | None = None

    @model_validator(mode="after")
    def _consumed_iff_it_has_an_attempt(self) -> Approval:
        consumed = self.status is ApprovalState.CONSUMED
        if consumed != (self.consumed_attempt_id is not None):
            raise ValueError("a consumed approval names its attempt, and only a consumed one")
        return self


class Attempt(Timestamped):
    """One logical payment attempt. There is never a second for one approval."""

    attempt_id: Id
    purchase_id: Id
    approval_id: Digest
    payment_key: Digest
    request_hash: Digest
    dispatch: DispatchState = DispatchState.READY
    started_at: datetime | None = None
    provider_reference: str | None = None
    next_check_at: datetime | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _started_iff_it_has_a_start_time(self) -> Attempt:
        """The dispatch marker and its timestamp cannot disagree.

        ``started`` is the record that a provider was called. If it could exist
        without a time, or a time without it, the ambiguity window would be
        unreadable after a crash -- the one moment it has to be readable.
        """
        started = self.dispatch is DispatchState.STARTED
        if started != (self.started_at is not None):
            raise ValueError("dispatch 'started' and started_at must agree")
        return self


class ProviderLookup(Record):
    """The uniqueness record that makes a duplicate payment impossible.

    One row per (provider, payment_key), created conditionally inside the
    approval transaction. It is also what a returning callback is matched
    against, so it carries the terms the provider is expected to report back.
    """

    provider: str = Field(min_length=1, max_length=64)
    payment_key: Digest
    purchase_id: Id
    attempt_id: Id
    expected_seller_id: str = Field(min_length=1, max_length=64)
    expected_amount: Money
    expected_currency: Currency = Currency.INR

    @property
    def unique_key(self) -> str:
        """The conditional-write key WP-07 uses: PROVIDER#<provider>#<key>."""
        return f"PROVIDER#{self.provider}#{self.payment_key}"

    def matches(self, *, seller_id: str, amount: Money, currency: Currency) -> bool:
        """Whether a reported fact is about the payment we actually made.

        A callback claiming a different amount is exactly the thing that must
        never quietly become truth, so WP-10 quarantines anything failing here.
        """
        return (
            seller_id == self.expected_seller_id
            and amount == self.expected_amount
            and currency == self.expected_currency
        )


class Purchase(Record):
    """The aggregate: one basket, three independent outcomes, one claim."""

    purchase_id: Id
    owner_id: Id
    basket_id: Id
    intent_revision: int = Field(ge=1)
    mode: Mode
    active_attempt_id: Id | None = None
    #: The most recent attempt, kept after the active one is cleared. Without it
    #: the exposure check has to infer a previous attempt from the payment state,
    #: which means inventing an id and assuming a dispatch state.
    last_attempt_id: Id | None = None
    #: How many times this purchase has been re-checked. A stale preparation
    #: means the shopper re-checks, so preparations must be able to accumulate.
    preparation_version: int = Field(default=0, ge=0)
    payment: PaymentState = PaymentState.NOT_STARTED
    order: OrderState = OrderState.NOT_CREATED
    refund: RefundState = RefundState.NONE
    claim: ClaimState = ClaimState.UNCLAIMED
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _a_claim_and_an_active_attempt_go_together(self) -> Purchase:
        if self.claim is ClaimState.CLAIMED and self.active_attempt_id is None:
            raise ValueError("a claimed purchase names its active attempt")
        if self.active_attempt_id is not None and self.claim is not ClaimState.CLAIMED:
            raise ValueError("an active attempt requires the purchase to be claimed")
        return self

    @property
    def is_resolved(self) -> bool:
        """Payment success alone is not resolution; order evidence is needed.

        SPEC section 8: "Resolution needs relevant order/refund evidence, not
        merely payment success."
        """
        if self.payment is PaymentState.FAILED:
            return True
        if self.payment is PaymentState.SUCCEEDED:
            return self.order in (OrderState.CONFIRMED, OrderState.FAILED)
        return False


def build_attempt_and_lookup(
    *,
    attempt_id: str,
    purchase: Purchase,
    approval: Approval,
    quote: CheckoutQuote,
    provider: str = "sim",
) -> tuple[Attempt, ProviderLookup]:
    """Derive the attempt and its uniqueness row from consent.

    Both keys come from identities fixed at approval time, so this is replay
    safe: calling it twice for the same approval produces identical records
    rather than a second attempt.
    """
    key = build_payment_key(purchase_id=purchase.purchase_id, approval_id=approval.approval_id)
    # The hash of the PAYMENT payload, not of the approve request. Checkout
    # rebuilds the payload and must reproduce this exactly before sending.
    payload_hash = build_payment_request_hash(
        payment_key=key,
        quote_hash=quote.quote_hash,
        seller_id=quote.demo_seller_id,
        amount_paise=quote.total.amount_paise,
        currency=str(quote.currency),
        expires_at=quote.expires_at,
    )
    attempt = Attempt(
        attempt_id=attempt_id,
        purchase_id=purchase.purchase_id,
        approval_id=approval.approval_id,
        payment_key=key,
        request_hash=payload_hash,
    )
    lookup = ProviderLookup(
        provider=provider,
        payment_key=key,
        purchase_id=purchase.purchase_id,
        attempt_id=attempt_id,
        expected_seller_id=quote.demo_seller_id,
        expected_amount=quote.total,
        expected_currency=quote.currency,
    )
    return attempt, lookup


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Approval",
    "Attempt",
    "AttemptSnapshot",
    "CheckoutQuote",
    "ProviderLookup",
    "Purchase",
    "QuoteLine",
    "build_attempt_and_lookup",
    "Change",
    "ChangeKind",
    "Diff",
    "EXPOSED_PAYMENT_STATES",
    "PREPARATION_FRESHNESS_SECONDS",
    "Preparation",
    "PurchaseSnapshot",
    "QUOTE_LIFETIME_SECONDS",
    "QuoteWindow",
    "build_diff",
    "can_build_quote",
    "check_quote_live",
    "has_unresolved_exposure",
    "is_fresh",
    "is_quote_live",
    "may_create_attempt",
    "quote_window",
]
