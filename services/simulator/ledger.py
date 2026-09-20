"""The simulator's own ledger (WP-09).

Separate table, separate records, one writer. The rules below are what make a
retry safe:

- An **unseen key** is checked against its own expiry and then recorded once.
- The **same key with the same payload** returns the original facts, forever,
  even after expiry and after any number of replays. This is what lets the
  checkout task resend without fear.
- The **same key with a different payload** conflicts and records nothing. Paired
  with WP-08 freezing ``request_hash`` at approval time, "approved Rs X,
  submitted Rs Y" is unreachable from both directions.

The scenario is captured on the record when it is written. An operator changing
the scenario afterwards does not retroactively change an effect that already
happened -- the ledger is a record of what occurred, not a view over current
settings. That matters during the demo, where scenarios get switched between runs
while earlier purchases are still on screen.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from services.domain.ids import Digest, Record, Timestamped
from services.domain.money import Currency, Money


class Scenario(StrEnum):
    """What the operator has asked the provider to do next."""

    SUCCESS = "success"
    DEFINITIVE_FAILURE = "definitive_failure"
    ACCEPT_THEN_TIMEOUT = "accept_then_timeout"
    PAID_ORDER_MISSING = "paid_order_missing"
    DUPLICATE_CALLBACK = "duplicate_callback"
    CONFLICTING_CALLBACK = "conflicting_callback"
    REFUND_PENDING_THEN_COMPLETE = "refund_pending_then_complete"


class LedgerStatus(StrEnum):
    """The provider's own vocabulary, which is not the domain's.

    ``expired_rejected`` has no domain equivalent: it means we did call, and were
    told no because the quote's expiry had passed. Mapping it is the checkout
    task's job, and the mapping is deliberately explicit rather than implied by a
    shared name.
    """

    ACCEPTED = "accepted"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED_REJECTED = "expired_rejected"


TERMINAL_STATUSES = frozenset(
    {LedgerStatus.SUCCEEDED, LedgerStatus.FAILED, LedgerStatus.EXPIRED_REJECTED}
)


class PaymentRecord(Timestamped):
    """One payment, as the provider remembers it. Immutable once terminal."""

    provider: str = Field(min_length=1, max_length=64)
    payment_key: Digest
    request_hash: Digest
    seller_id: str = Field(min_length=1, max_length=64)
    amount: Money
    currency: Currency = Currency.INR
    expires_at: datetime
    status: LedgerStatus
    provider_reference: str | None = None
    scenario: Scenario = Scenario.SUCCESS
    #: False only for a rejection. Counting these is how the demo proves that one
    #: approval produced one effect.
    effect_recorded: bool = True
    created_at: datetime

    @model_validator(mode="after")
    def _a_rejection_records_no_effect(self) -> PaymentRecord:
        if self.status is LedgerStatus.EXPIRED_REJECTED and self.effect_recorded:
            raise ValueError("an expired rejection must not record an effect")
        if self.status is not LedgerStatus.EXPIRED_REJECTED and not self.effect_recorded:
            raise ValueError("an accepted payment records an effect")
        return self

    @model_validator(mode="after")
    def _an_accepted_payment_has_a_reference(self) -> PaymentRecord:
        if self.effect_recorded and not self.provider_reference:
            raise ValueError("an accepted payment carries a provider reference")
        return self


class OrderRecord(Timestamped):
    """An order at the provider. Created only after a payment succeeded."""

    provider: str = Field(min_length=1, max_length=64)
    order_key: Digest
    payment_reference: str = Field(min_length=1, max_length=128)
    quote_hash: Digest
    status: str = Field(default="confirmed", min_length=1, max_length=32)
    order_reference: str = Field(min_length=1, max_length=128)
    created_at: datetime


class RefundRecord(Timestamped):
    """A refund. Only ever created by the operator's scenario, never by us."""

    provider: str = Field(min_length=1, max_length=64)
    refund_reference: str = Field(min_length=1, max_length=128)
    payment_reference: str = Field(min_length=1, max_length=128)
    amount: Money
    status: str = Field(min_length=1, max_length=32)
    created_at: datetime


class EffectCounts(Record):
    """What the demo displays, read straight off the ledger.

    ``payment_effects`` must equal the number of attempts that were dispatched,
    over the whole run. Any other number is the story falling apart.
    """

    payment_effects: int = 0
    order_effects: int = 0
    submissions_received: int = 0
    duplicate_submissions_suppressed: int = 0
    rejections: int = 0
    callbacks_sent: int = 0


__all__ = [
    "TERMINAL_STATUSES",
    "EffectCounts",
    "LedgerStatus",
    "OrderRecord",
    "PaymentRecord",
    "RefundRecord",
    "Scenario",
]
