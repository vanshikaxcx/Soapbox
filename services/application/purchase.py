"""Purchase use cases: prepare, accept, approve, cancel (WP-08).

The consent boundary. Everything before it is browsing; everything after it is
money.

Two claims a judge will test here, and where each is settled:

1. "I tapped approve twice and there is still one attempt" -- settled by the
   transaction in ``approve``, specifically the ``ProviderLookup`` write with a
   must-not-exist guard. Not by UI state, not by a lock.
2. "The amount I approved is the amount that was submitted" -- settled by
   ``quote.verify`` here and by ``request_hash`` being frozen onto the attempt,
   which WP-09 re-asserts before it sends anything.

No rule is implemented in this module. Every decision is a call into
services.domain; what lives here is ordering, authorization, and assembling the
writes that must commit together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from services.application.ports import (
    Action,
    Clock,
    Condition,
    IdFactory,
    Key,
    MerchantPort,
    PolicyPort,
    StateStore,
    Write,
    read,
)
from services.application.prepare import (
    REFRESH_DEADLINE_SECONDS,
    RefreshedFacts,
    build_quote,
    diff_between,
    refresh_line,
)
from services.domain.basket import Basket
from services.domain.canonical import TAG_IDEMPOTENCY, digest
from services.domain.errors import (
    ApprovalExpired,
    AttemptBlockedByExposure,
    DiffHashMismatch,
    DomainError,
    IdempotencyPayloadMismatch,
    InvalidRecord,
    PreparationExpired,
    PurchaseAlreadyClaimed,
    VersionConflict,
)
from services.domain.evidence import Evidence, EvidenceKind
from services.domain.ids import Id, Record
from services.domain.jobs import Job, JobType, OutboxEvent
from services.domain.keys import approval_id as derive_approval_id
from services.domain.keys import idempotency_request_hash
from services.domain.money import Charge, ChargeKind
from services.domain.purchase import (
    Approval,
    Attempt,
    AttemptSnapshot,
    CheckoutQuote,
    Diff,
    Preparation,
    Purchase,
    PurchaseSnapshot,
    build_attempt_and_lookup,
    check_quote_live,
    is_fresh,
    may_create_attempt,
)
from services.domain.transitions import (
    ApprovalState,
    ClaimState,
    DispatchState,
    PaymentState,
)

PROVIDER = "sim"


# -- keys ------------------------------------------------------------------
#
# Key shapes are P4's to confirm in WP-07; they are named here so both sides
# agree on what a conditional write is guarding.


def purchase_key(purchase_id: str) -> Key:
    return (f"PURCHASE#{purchase_id}", "PURCHASE")


def approval_key(purchase_id: str, approval_id: str) -> Key:
    return (f"PURCHASE#{purchase_id}", f"APPROVAL#{approval_id}")


def attempt_key(purchase_id: str, attempt_id: str) -> Key:
    return (f"PURCHASE#{purchase_id}", f"ATTEMPT#{attempt_id}")


def quote_key(purchase_id: str, quote_id: str) -> Key:
    return (f"PURCHASE#{purchase_id}", f"QUOTE#{quote_id}")


def preparation_key(purchase_id: str, version: int) -> Key:
    return (f"PURCHASE#{purchase_id}", f"PREPARATION#{version}")


def facts_key(purchase_id: str, version: int) -> Key:
    """The refreshed facts a preparation was built from.

    Stored separately and immutably so the quote is built from what the merchant
    actually said, not from whatever the basket happens to hold by then.
    """
    return (f"PURCHASE#{purchase_id}", f"FACTS#{version}")


def provider_lookup_key(payment_key: str) -> Key:
    return (f"PROVIDER#{PROVIDER}#{payment_key}", "LOOKUP")


def active_basket_key(basket_id: str) -> Key:
    """One active purchase per basket (WP-08 D-6).

    Idempotency keys alone do not close this: two different keys would create two
    purchases for one basket, each separately approvable, each producing a real
    payment.
    """
    return (f"BASKET#{basket_id}", "ACTIVE_PURCHASE")


def idempotency_key(owner_id: str, endpoint: str, key: str) -> Key:
    """Scoped per owner and endpoint so two shoppers cannot collide."""
    return (f"USER#{owner_id}", f"IDEMPOTENCY#{endpoint}#{key}")


def job_key(job_id: str) -> Key:
    return (f"JOB#{job_id}", "JOB")


def outbox_key(event_id: str) -> Key:
    return (f"OUTBOX#{event_id}", "EVENT")


def evidence_key(purchase_id: str, evidence_id: str) -> Key:
    return (f"PURCHASE#{purchase_id}", f"EVIDENCE#{evidence_id}")


# -- results ---------------------------------------------------------------


class IdempotencyRecord(Record):
    """What a replay returns instead of re-executing.

    Carries the job id as well as the result, because a client replaying an
    approve still needs a status URL to poll -- handing back only the attempt
    would make a retry look different from the original call.
    """

    request_hash: str
    result_ref: str
    job_id: Id | None = None


class PurchaseCreated(Record):
    purchase_id: Id
    job_id: Id
    already_existed: bool = False


class PreparationAccepted(Record):
    preparation_version: int
    quote: CheckoutQuote


class AttemptCreated(Record):
    """One logical attempt. ``replayed`` means it already existed.

    ``job_id`` is None only when the attempt is recovered through a consumed
    approval rather than an idempotency record -- the work is already in flight
    and the client should poll the purchase.
    """

    attempt_id: Id
    job_id: Id | None
    payment_key: str
    replayed: bool = False


class PurchaseCancelled(Record):
    purchase_id: Id
    version: int


@dataclass(frozen=True, slots=True)
class NotFound(DomainError):
    """Owner mismatch and genuinely-absent records are indistinguishable.

    Deliberate: someone probing purchase ids must not be able to tell the
    difference between "not yours" and "does not exist".
    """

    code: ClassVar[str] = "not_found"
    what: str


# -- the use cases ---------------------------------------------------------


class PurchaseUseCases:
    """Ordering, authorization and transaction assembly. No rules of its own."""

    def __init__(
        self,
        *,
        store: StateStore,
        clock: Clock,
        ids: IdFactory,
        policy: PolicyPort,
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._policy = policy

    # -- create ------------------------------------------------------------

    def create_purchase(
        self,
        *,
        owner_id: str,
        basket: Basket,
        intent_revision: int,
        idempotency: str,
    ) -> PurchaseCreated | DomainError:
        if not self._policy.allows(owner_id, Action.CREATE_PURCHASE, basket.basket_id):
            return NotFound("basket")

        idem_key = idempotency_key(owner_id, "create_purchase", idempotency)
        stored = self._store.get(idem_key)
        if isinstance(stored, IdempotencyRecord):
            # A replay. Without this read the write below would trip its own
            # must-not-exist guard and surface as a confusing conflict.
            return PurchaseCreated(
                purchase_id=stored.result_ref,
                job_id=stored.job_id or stored.result_ref,
                already_existed=True,
            )

        existing_active = read(self._store, active_basket_key(basket.basket_id), _ActivePurchase)
        if existing_active is not None:
            # A second create for the same basket returns the purchase that is
            # already live rather than a second approvable one.
            return PurchaseCreated(
                purchase_id=existing_active.purchase_id,
                job_id=existing_active.job_id,
                already_existed=True,
            )

        purchase_id = self._ids.new_id("purchase")
        job_id = self._ids.new_id("job")
        event_id = self._ids.new_id("event")
        now = self._clock.now()

        purchase = Purchase(
            purchase_id=purchase_id,
            owner_id=owner_id,
            basket_id=basket.basket_id,
            intent_revision=intent_revision,
            mode=basket.mode,
        )
        job = Job(
            job_id=job_id,
            owner_id=owner_id,
            job_type=JobType.PREPARE,
            input_hash=digest(TAG_IDEMPOTENCY, {"basket_id": basket.basket_id}),
            reference=purchase_id,
            created_at=now,
        )
        writes = [
            Write(
                key=purchase_key(purchase_id),
                item=purchase,
                condition=Condition.MUST_NOT_EXIST,
                reason="create the purchase once",
            ),
            Write(
                key=active_basket_key(basket.basket_id),
                item=_ActivePurchase(purchase_id=purchase_id, job_id=job_id),
                condition=Condition.MUST_NOT_EXIST,
                reason="one active purchase per basket",
            ),
            Write(
                key=job_key(job_id),
                item=job,
                condition=Condition.MUST_NOT_EXIST,
                reason="durable commit before any work",
            ),
            Write(
                key=outbox_key(event_id),
                item=OutboxEvent(
                    event_id=event_id,
                    event_type="purchase.prepare_requested",
                    aggregate_id=purchase_id,
                    aggregate_version=1,
                    owner_id=owner_id,
                    occurred_at=now,
                    reference=job_id,
                ),
                condition=Condition.MUST_NOT_EXIST,
                reason="work is dispatched only from committed state",
            ),
            Write(
                key=idem_key,
                item=IdempotencyRecord(
                    request_hash=idempotency_request_hash(
                        method="POST",
                        path_template="/purchases",
                        path_params={},
                        owner_id=owner_id,
                        body={"basket_id": basket.basket_id},
                    ),
                    result_ref=purchase_id,
                    job_id=job_id,
                ),
                condition=Condition.MUST_NOT_EXIST,
                reason="replay returns, never re-executes",
            ),
        ]
        failure = self._store.transact(writes)
        if failure is not None:
            # Someone else created it in the gap between our read and our write.
            active = read(self._store, active_basket_key(basket.basket_id), _ActivePurchase)
            if active is not None:
                return PurchaseCreated(
                    purchase_id=active.purchase_id, job_id=active.job_id, already_existed=True
                )
            return failure
        return PurchaseCreated(purchase_id=purchase_id, job_id=job_id)

    # -- prepare -----------------------------------------------------------

    def prepare(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        basket: Basket,
        merchant: MerchantPort,
        location: str,
        delivery: str = "standard",
        deadline_seconds: int = REFRESH_DEADLINE_SECONDS,
    ) -> tuple[Preparation, Diff] | DomainError:
        """Re-check the basket with the merchant and record what changed.

        A line whose refresh fails becomes unknown. The price from the original
        search is never substituted: it would produce an exact-looking total that
        nobody has verified, which is the one thing this package must not do.

        Preparations accumulate. A stale one means the shopper re-checks, so the
        version comes from the purchase and advances under a conditional write --
        two concurrent re-checks cannot land on the same version.
        """
        purchase = self._owned_purchase(owner_id, purchase_id)
        if isinstance(purchase, DomainError):
            return purchase

        refreshed = tuple(
            refresh_line(merchant, line=line, location=location, deadline_seconds=deadline_seconds)
            for line in basket.lines
        )

        assessed = merchant.assess_fees(
            location,
            basket.merchant_id,
            basket.fee_assessment.line_hash if basket.fee_assessment else "",
            deadline_seconds,
        )
        if isinstance(assessed, DomainError):
            # We could not establish the fees. Unknown, never zero, and never the
            # fee we happened to see during the search.
            charges = tuple(
                Charge.unknown_charge(c.kind)
                for c in (basket.fee_assessment.charges if basket.fee_assessment else ())
            ) or (Charge.unknown_charge(ChargeKind.DELIVERY),)
        else:
            charges = tuple(assessed)

        version = purchase.preparation_version + 1
        now = self._clock.now()
        facts = RefreshedFacts(
            purchase_id=purchase_id,
            merchant_id=basket.merchant_id,
            mode=basket.mode,
            location=location,
            delivery=delivery,
            lines=refreshed,
            charges=charges,
            refreshed_at=now,
        )
        diff = diff_between(basket, facts)
        preparation = Preparation(
            preparation_id=self._ids.new_id("prep"),
            purchase_id=purchase_id,
            refreshed_at=now,
            diff_hash=diff.hash(),
            change_count=len(diff.changes),
            version=version,
        )
        advanced = purchase.model_copy(
            update={
                "preparation_version": version,
                "version": purchase.version + 1,
            }
        )
        failure = self._store.transact(
            [
                Write(
                    key=preparation_key(purchase_id, version),
                    item=preparation,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="preparations are immutable",
                ),
                Write(
                    key=facts_key(purchase_id, version),
                    item=facts,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="the facts the quote is built from",
                ),
                Write(
                    key=purchase_key(purchase_id),
                    item=advanced,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=purchase.version,
                    reason="advance the preparation counter exactly once",
                ),
            ]
        )
        if failure is not None:
            return failure
        return preparation, diff

    def accept_preparation(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        version: int,
        diff_hash: str,
        expected_purchase_version: int,
    ) -> PreparationAccepted | DomainError:
        """Accept an exact change list, and build the quote if still fresh.

        The anti-loop rule lives here: once the diff is accepted and the
        preparation is still fresh, the quote is built WITHOUT another refresh.
        Re-refreshing at this point is what turns recheck into a loop, because
        every refresh can produce a new diff to accept.
        """
        if not self._policy.allows(owner_id, Action.ACCEPT_PREPARATION, purchase_id):
            return NotFound("purchase")

        purchase = self._owned_purchase(owner_id, purchase_id)
        if isinstance(purchase, DomainError):
            return purchase
        if purchase.version != expected_purchase_version:
            return VersionConflict(expected=expected_purchase_version, actual=purchase.version)

        preparation = read(self._store, preparation_key(purchase_id, version), Preparation)
        if preparation is None:
            return NotFound("preparation")
        if preparation.diff_hash != diff_hash:
            # A shopper can only accept the change list they were shown.
            return DiffHashMismatch(expected=preparation.diff_hash, submitted=diff_hash)

        now = self._clock.now()
        if not is_fresh(preparation, now):
            return PreparationExpired(preparation_id=preparation.preparation_id)

        facts = read(self._store, facts_key(purchase_id, version), RefreshedFacts)
        if facts is None:
            return NotFound("refreshed facts")

        accepted = preparation.model_copy(
            update={"accepted_diff_hash": diff_hash, "version": preparation.version + 1}
        )
        # Built from the stored facts, with no second refresh. Re-refreshing here
        # is what turns recheck into a loop, because every refresh can produce a
        # new diff to accept.
        quote = build_quote(
            purchase=purchase,
            preparation=accepted,
            facts=facts,
            quote_id=self._ids.new_id("quote"),
            quote_version=version,
            now=now,
        )
        if isinstance(quote, DomainError):
            return quote

        writes = [
            Write(
                key=preparation_key(purchase_id, version),
                item=accepted,
                condition=Condition.VERSION_MUST_BE,
                expected_version=preparation.version,
                reason="record the acceptance once",
            ),
            Write(
                key=quote_key(purchase_id, quote.quote_id),
                item=quote,
                condition=Condition.MUST_NOT_EXIST,
                reason="quotes are immutable",
            ),
        ]
        failure = self._store.transact(writes)
        if failure is not None:
            return failure
        return PreparationAccepted(preparation_version=accepted.version, quote=quote)

    # -- approve -----------------------------------------------------------

    def approve(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        quote_id: str,
        quote_hash: str,
        quote_version: int,
        expected_purchase_version: int,
        idempotency: str,
    ) -> AttemptCreated | DomainError:
        """The one path that turns consent into a payment attempt.

        The validation order below is part of the contract, not an accident:
        P1 shows different copy for each failure, so which error wins when two
        apply has to be deterministic.
        """
        endpoint = "approve"
        body = {
            "quote_id": quote_id,
            "quote_hash": quote_hash,
            "quote_version": quote_version,
            "expected_purchase_version": expected_purchase_version,
        }
        request_hash = idempotency_request_hash(
            method="POST",
            path_template="/purchases/{id}/approve",
            path_params={"id": purchase_id},
            owner_id=owner_id,
            body=body,
        )

        # 1-2. owner, then policy. Both conceal as 404.
        purchase = self._owned_purchase(owner_id, purchase_id)
        if isinstance(purchase, DomainError):
            return purchase
        if not self._policy.allows(owner_id, Action.APPROVE_PURCHASE, purchase_id):
            return NotFound("purchase")

        # 3. idempotency
        idem_key = idempotency_key(owner_id, endpoint, idempotency)
        stored = read(self._store, idem_key, IdempotencyRecord)
        if stored is not None:
            if stored.request_hash != request_hash:
                return IdempotencyPayloadMismatch(key=idempotency)
            return self._replay(purchase_id, stored.result_ref, job_id=stored.job_id)

        # 4. expected version
        if purchase.version != expected_purchase_version:
            return VersionConflict(expected=expected_purchase_version, actual=purchase.version)

        # 5-6. the quote exists, belongs here, and is the version submitted
        quote = read(self._store, quote_key(purchase_id, quote_id), CheckoutQuote)
        if quote is None or quote.owner_id != owner_id:
            return NotFound("quote")
        if quote.quote_version != quote_version:
            return VersionConflict(expected=quote_version, actual=quote.quote_version)

        # 7. the terms still hash to what was shown, and to what was submitted
        mismatch = quote.verify(quote_hash)
        if mismatch is not None:
            return mismatch

        # 8. expiry, on the server clock
        now = self._clock.now()
        expired = check_quote_live(quote_id, quote.window, now)
        if expired is not None:
            return expired

        # 9. consent is one-shot; a repeat returns the attempt it already made
        consent_id = derive_approval_id(
            quote_id=quote.quote_id,
            quote_hash=quote.quote_hash,
            quote_version=quote.quote_version,
        )
        existing_raw = self._store.get(approval_key(purchase_id, consent_id))
        existing = existing_raw if isinstance(existing_raw, Approval) else None
        if existing_raw is not None and existing is None:
            # A corrupted or unexpected record where consent should be. Refusing
            # is the only safe answer: we cannot tell whether money already moved.
            return InvalidRecord(record="approval", detail="unexpected record shape")
        if existing is not None and existing.status is ApprovalState.CONSUMED:
            return self._replay(purchase_id, existing.consumed_attempt_id, replayed=True)

        # 10. an unresolved or paid previous attempt blocks a replacement
        blocked = may_create_attempt(self._snapshot(purchase))
        if isinstance(blocked, AttemptBlockedByExposure):
            return blocked

        return self._commit_approval(
            purchase=purchase,
            quote=quote,
            consent_id=consent_id,
            request_hash=request_hash,
            idem_key=idem_key,
            now=now,
        )

    def _commit_approval(
        self,
        *,
        purchase: Purchase,
        quote: CheckoutQuote,
        consent_id: str,
        request_hash: str,
        idem_key: Key,
        now: datetime,
    ) -> AttemptCreated | DomainError:
        attempt_id = self._ids.new_id("attempt")
        job_id = self._ids.new_id("job")
        event_id = self._ids.new_id("event")
        evidence_id = self._ids.new_id("evidence")

        approval = Approval(
            approval_id=consent_id,
            quote_id=quote.quote_id,
            quote_hash=quote.quote_hash,
            quote_version=quote.quote_version,
            purchase_version=purchase.version,
            owner_id=purchase.owner_id,
            status=ApprovalState.CONSUMED,
            consumed_attempt_id=attempt_id,
        )
        attempt, lookup = build_attempt_and_lookup(
            attempt_id=attempt_id,
            purchase=purchase,
            approval=approval,
            quote=quote,
            provider=PROVIDER,
        )
        claimed = purchase.model_copy(
            update={
                "active_attempt_id": attempt_id,
                "last_attempt_id": attempt_id,
                "claim": ClaimState.CLAIMED,
                "payment": PaymentState.CLAIMED,
                "version": purchase.version + 1,
            }
        )
        job = Job(
            job_id=job_id,
            owner_id=purchase.owner_id,
            job_type=JobType.CHECKOUT,
            input_hash=request_hash,
            reference=attempt_id,
            created_at=now,
        )

        # The eight writes. All of them, or none.
        writes = [
            Write(
                key=approval_key(purchase.purchase_id, consent_id),
                item=approval,
                condition=Condition.MUST_NOT_EXIST,
                reason="consent is one-shot",
            ),
            Write(
                key=attempt_key(purchase.purchase_id, attempt_id),
                item=attempt,
                condition=Condition.MUST_NOT_EXIST,
                reason="the attempt is created once",
            ),
            Write(
                key=provider_lookup_key(attempt.payment_key),
                item=lookup,
                condition=Condition.MUST_NOT_EXIST,
                reason="THE uniqueness guarantee: no duplicate payment key",
            ),
            Write(
                key=purchase_key(purchase.purchase_id),
                item=claimed,
                condition=Condition.VERSION_MUST_BE,
                expected_version=purchase.version,
                reason="wins or loses the cancel race, atomically",
            ),
            Write(
                key=job_key(job_id),
                item=job,
                condition=Condition.MUST_NOT_EXIST,
                reason="durable commit before any provider call",
            ),
            Write(
                key=outbox_key(event_id),
                item=OutboxEvent(
                    event_id=event_id,
                    event_type="purchase.checkout_requested",
                    aggregate_id=purchase.purchase_id,
                    aggregate_version=claimed.version,
                    owner_id=purchase.owner_id,
                    occurred_at=now,
                    reference=job_id,
                ),
                condition=Condition.MUST_NOT_EXIST,
                reason="checkout is dispatched only from committed state",
            ),
            Write(
                key=evidence_key(purchase.purchase_id, evidence_id),
                item=Evidence(
                    evidence_id=evidence_id,
                    purchase_id=purchase.purchase_id,
                    kind=EvidenceKind.APPROVAL,
                    source_ref=quote.quote_id,
                    observed_at=now,
                    payload_hash=quote.quote_hash,
                ),
                condition=Condition.MUST_NOT_EXIST,
                reason="the consent record a case can cite",
            ),
            Write(
                key=idem_key,
                item=IdempotencyRecord(
                    request_hash=request_hash, result_ref=attempt_id, job_id=job_id
                ),
                condition=Condition.MUST_NOT_EXIST,
                reason="replay returns, never re-executes",
            ),
        ]

        failure = self._store.transact(writes)
        if failure is not None:
            # Lost a race. Report what actually happened rather than an error:
            # if the winner was another approval of the same consent, the
            # shopper's payment is in flight and telling them it failed would be
            # the precise lie this product exists to argue against.
            settled = read(self._store, approval_key(purchase.purchase_id, consent_id), Approval)
            if settled is not None and settled.status is ApprovalState.CONSUMED:
                return self._replay(
                    purchase.purchase_id, settled.consumed_attempt_id, replayed=True
                )
            replay = read(self._store, idem_key, IdempotencyRecord)
            if replay is not None:
                return self._replay(
                    purchase.purchase_id, replay.result_ref, replayed=True, job_id=replay.job_id
                )
            return failure

        return AttemptCreated(attempt_id=attempt_id, job_id=job_id, payment_key=attempt.payment_key)

    # -- cancel ------------------------------------------------------------

    def cancel(
        self, *, owner_id: str, purchase_id: str, expected_purchase_version: int
    ) -> PurchaseCancelled | DomainError:
        """Competes with approve on the same purchase version.

        Exactly one of the two commits, so a shopper can never end up with both
        an attempt and a cancellation.
        """
        if not self._policy.allows(owner_id, Action.CANCEL_PURCHASE, purchase_id):
            return NotFound("purchase")

        purchase = self._owned_purchase(owner_id, purchase_id)
        if isinstance(purchase, DomainError):
            return purchase
        if purchase.version != expected_purchase_version:
            return VersionConflict(expected=expected_purchase_version, actual=purchase.version)
        if purchase.claim is ClaimState.CLAIMED:
            # There is an attempt. We cannot know whether a provider call is in
            # flight, so there is nothing safe to cancel.
            return PurchaseAlreadyClaimed(
                purchase_id=purchase_id, attempt_id=purchase.active_attempt_id or "unknown"
            )

        cancelled = purchase.model_copy(update={"version": purchase.version + 1})
        writes = [
            Write(
                key=purchase_key(purchase_id),
                item=cancelled,
                condition=Condition.VERSION_MUST_BE,
                expected_version=purchase.version,
                reason="wins or loses the approve race, atomically",
            ),
            Write(
                key=active_basket_key(purchase.basket_id),
                item=None,
                condition=Condition.NONE,
                reason="release the basket for a fresh purchase",
            ),
        ]
        failure = self._store.transact(writes)
        if failure is not None:
            return failure
        return PurchaseCancelled(purchase_id=purchase_id, version=cancelled.version)

    # -- expiry ------------------------------------------------------------

    def expire_unsent(self, *, purchase_id: str, attempt_id: str) -> Attempt | DomainError:
        """Mark an attempt that expired before any provider call (WP-08 D-4).

        Evaluated by the checkout task on pickup rather than by a scheduled
        sweep, so no timer infrastructure is required. The condition on
        ``dispatch = ready`` is what makes it safe: if the task already started
        the call, this loses and the outcome is decided by provider facts.
        """
        attempt = read(self._store, attempt_key(purchase_id, attempt_id), Attempt)
        if attempt is None:
            return NotFound("attempt")
        if attempt.dispatch is not DispatchState.READY:
            return ApprovalExpired(approval_id=attempt.approval_id)

        purchase = read(self._store, purchase_key(purchase_id), Purchase)
        if purchase is None:
            return NotFound("purchase")

        expired = attempt.model_copy(
            update={
                "dispatch": DispatchState.EXPIRED_UNSENT,
                "version": attempt.version + 1,
            }
        )
        released = purchase.model_copy(
            update={
                "active_attempt_id": None,
                "claim": ClaimState.RELEASED,
                "payment": PaymentState.NOT_STARTED,
                "version": purchase.version + 1,
            }
        )
        writes = [
            Write(
                key=attempt_key(purchase_id, attempt_id),
                item=expired,
                condition=Condition.VERSION_MUST_BE,
                expected_version=attempt.version,
                reason="only if nothing has started the call",
            ),
            Write(
                key=purchase_key(purchase_id),
                item=released,
                condition=Condition.VERSION_MUST_BE,
                expected_version=purchase.version,
                reason="release the claim",
            ),
            Write(
                key=active_basket_key(purchase.basket_id),
                item=None,
                condition=Condition.NONE,
                reason="the shopper may buy this basket again",
            ),
        ]
        # The ProviderLookup row is deliberately NOT deleted. The key is spent;
        # a fresh approval means a new quote, so a new approval id and key.
        failure = self._store.transact(writes)
        return failure if failure is not None else expired

    # -- read --------------------------------------------------------------

    def read(self, *, owner_id: str, purchase_id: str) -> Purchase | DomainError:
        if not self._policy.allows(owner_id, Action.READ_PURCHASE, purchase_id):
            return NotFound("purchase")
        return self._owned_purchase(owner_id, purchase_id)

    def approve_enabled(self, *, purchase: Purchase, quote: CheckoutQuote | None) -> bool:
        """Whether P1 may enable the approve control.

        Computed on the server and sent as a boolean, so the browser never
        derives it from timestamps. A client-side countdown can otherwise
        re-enable the button in the gap between "looks expired" and the
        transition actually committing.
        """
        if quote is None:
            return False
        if check_quote_live(quote.quote_id, quote.window, self._clock.now()) is not None:
            return False
        return may_create_attempt(self._snapshot(purchase)) is None

    # -- helpers -----------------------------------------------------------

    def _owned_purchase(self, owner_id: str, purchase_id: str) -> Purchase | DomainError:
        purchase = read(self._store, purchase_key(purchase_id), Purchase)
        if purchase is None or purchase.owner_id != owner_id:
            return NotFound("purchase")
        return purchase

    def _snapshot(self, purchase: Purchase) -> PurchaseSnapshot:
        """Read the real attempts rather than inferring one from payment state.

        An earlier version invented an attempt id and assumed ``dispatch=started``
        whenever the payment was not ``not_started``. The blocking decision came
        out right, but it was a guess about a record the purchase did not
        remember -- so the purchase now remembers it.
        """
        return PurchaseSnapshot(
            active_attempt=self._attempt_snapshot(purchase, purchase.active_attempt_id),
            last_attempt=self._attempt_snapshot(purchase, purchase.last_attempt_id),
        )

    def _attempt_snapshot(
        self, purchase: Purchase, attempt_id: str | None
    ) -> AttemptSnapshot | None:
        if attempt_id is None:
            return None
        stored = read(self._store, attempt_key(purchase.purchase_id, attempt_id), Attempt)
        if stored is None:
            return None
        return AttemptSnapshot(
            attempt_id=stored.attempt_id, dispatch=stored.dispatch, payment=purchase.payment
        )

    def _replay(
        self,
        purchase_id: str,
        attempt_id: str | None,
        replayed: bool = True,
        job_id: str | None = None,
    ) -> AttemptCreated | DomainError:
        if attempt_id is None:
            return InvalidRecord(record="approval", detail="consumed without an attempt")
        attempt = read(self._store, attempt_key(purchase_id, attempt_id), Attempt)
        if attempt is None:
            return NotFound("attempt")
        return AttemptCreated(
            attempt_id=attempt.attempt_id,
            job_id=job_id,
            payment_key=attempt.payment_key,
            replayed=replayed,
        )


class _ActivePurchase(Record):
    purchase_id: Id
    job_id: Id


__all__ = [
    "AttemptCreated",
    "IdempotencyRecord",
    "NotFound",
    "PreparationAccepted",
    "PurchaseCancelled",
    "PurchaseCreated",
    "PurchaseUseCases",
    "active_basket_key",
    "approval_key",
    "attempt_key",
    "evidence_key",
    "idempotency_key",
    "job_key",
    "outbox_key",
    "preparation_key",
    "provider_lookup_key",
    "purchase_key",
    "quote_key",
]
