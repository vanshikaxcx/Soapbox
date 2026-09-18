"""Inbox events, evidence and cases (WP-02).

``InboxEvent`` is immutable once received: the raw body hash is recorded before
anything is applied, so a redelivery can be recognised and a tampered redelivery
can be told apart from an honest one.

``Case`` records what we know and what we do not. The missing-facts list is a
first-class field rather than an absence, because "we don't know whether an order
exists" is the thing the shopper most needs said out loud.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.domain.ids import Digest, Id, Timestamped
from services.domain.transitions import CaseState, InboxState


class FactKind(StrEnum):
    PAYMENT = "payment"
    ORDER = "order"
    REFUND = "refund"


class EvidenceKind(StrEnum):
    APPROVAL = "approval"
    DISPATCH = "dispatch"
    PROVIDER_FACT = "provider_fact"
    CALLBACK = "callback"
    MERCHANT_OBSERVATION = "merchant_observation"
    RECONCILIATION = "reconciliation"


class InboxEvent(Timestamped):
    """A provider callback, recorded before it is trusted or applied."""

    provider: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=128)
    body_hash: Digest
    delivery_timestamp: datetime
    received_at: datetime
    kind: FactKind
    key: str = Field(min_length=1, max_length=128)
    status: InboxState = InboxState.RECEIVED


def is_duplicate(existing: InboxEvent, incoming_body_hash: str) -> bool:
    """Same event, same bytes: a redelivery we can safely ignore."""
    return existing.body_hash == incoming_body_hash


def is_conflicting(existing: InboxEvent, incoming_body_hash: str) -> bool:
    """Same event id, different bytes: never applied, always flagged."""
    return existing.body_hash != incoming_body_hash


class Evidence(Timestamped):
    """Something that happened, with a pointer to where it can be checked."""

    evidence_id: Id
    purchase_id: Id
    kind: EvidenceKind
    source_ref: str = Field(min_length=1, max_length=512)
    observed_at: datetime
    payload_hash: Digest | None = None


class MissingFact(StrEnum):
    """What we could not establish. Named, so the UI never has to invent wording."""

    PAYMENT_OUTCOME = "payment_outcome"
    ORDER_EXISTENCE = "order_existence"
    ORDER_REFERENCE = "order_reference"
    REFUND_OUTCOME = "refund_outcome"
    MERCHANT_CONFIRMATION = "merchant_confirmation"


class Case(Timestamped):
    """An unresolved purchase, with its evidence and its gaps."""

    case_id: Id
    purchase_id: Id
    owner_id: Id
    opened_at: datetime
    known_facts: tuple[FactKind, ...] = ()
    missing_facts: tuple[MissingFact, ...] = ()
    guidance_versions: tuple[str, ...] = ()
    evidence_ids: tuple[Id, ...] = ()
    draft_ref: str | None = None
    status: CaseState = CaseState.OPEN
    version: int = Field(default=1, ge=1)

    @property
    def has_gaps(self) -> bool:
        return bool(self.missing_facts)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Case",
    "Evidence",
    "EvidenceKind",
    "FactKind",
    "InboxEvent",
    "MissingFact",
    "is_conflicting",
    "is_duplicate",
]
