"""Purchase use cases (WP-08 acceptance criteria 1-16).

The concurrency tests here are the point of the package. They interleave two
callers at the exact instant that can expose a race -- after both have read,
before either has committed -- using the store's ``before_transact`` hook rather
than sleeps, so they are deterministic and fast.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.application.fakes import (
    AllowAllPolicy,
    DenyPolicy,
    FixedClock,
    MemoryStore,
    SequentialIds,
)
from services.application.ports import Action, ConditionFailed, PolicyPort, read
from services.application.purchase import (
    AttemptCreated,
    IdempotencyRecord,
    NotFound,
    PurchaseCancelled,
    PurchaseCreated,
    PurchaseUseCases,
    active_basket_key,
    approval_key,
    attempt_key,
    idempotency_key,
    provider_lookup_key,
    purchase_key,
    quote_key,
)
from services.domain.basket import Basket, BasketLine, FeeAssessment, build_basket
from services.domain.errors import (
    DomainError,
    IdempotencyPayloadMismatch,
    PurchaseAlreadyClaimed,
    QuoteExpired,
    QuoteHashMismatch,
    VersionConflict,
)
from services.domain.ids import Mode
from services.domain.keys import approval_id as derive_approval_id
from services.domain.keys import quote_hash as build_quote_hash
from services.domain.money import Amount, Charge, ChargeKind, Currency, Money
from services.domain.purchase import (
    Attempt,
    CheckoutQuote,
    ProviderLookup,
    Purchase,
    QuoteLine,
    quote_window,
)
from services.domain.transitions import ClaimState, DispatchState, PaymentState

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
OWNER = "owner-0001"


# -- fixtures --------------------------------------------------------------


def a_basket(basket_id: str = "basket-0001") -> Basket:
    line = BasketLine(
        item_id="item-0001",
        observation_id="obs-00001",
        merchant_id="merchant-b",
        sku="rice-b",
        name="Basmati rice 5kg",
        pack_counts=(("rice-b", 1),),
        selected_base_units=5000,
        pack_base_units=5000,
        unit_price=Money.paise(58_000),
        line_total=Amount.known(Money.paise(58_000)),
    )
    return build_basket(
        basket_id=basket_id,
        search_id="search-0001",
        merchant_id="merchant-b",
        mode=Mode.LIVE,
        lines=(line,),
        fee_assessment=FeeAssessment(
            merchant_id="merchant-b",
            location="Indiranagar, Bengaluru",
            line_hash="a" * 64,
            subtotal=Money.paise(58_000),
            assessed_at=NOW,
            charges=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
        ),
    )


def a_quote(
    purchase_id: str, *, issued_at: datetime = NOW, version: int = 1, purchase_version: int = 1
) -> CheckoutQuote:
    lines = (
        QuoteLine(
            sku="rice-b",
            name="Basmati rice 5kg",
            quantity_base=5000,
            dimension="mass",
            unit_price=Money.paise(58_000),
            line_total=Money.paise(58_000),
        ),
    )
    charges = (Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),)
    window = quote_window(issued_at)
    terms: dict[str, Any] = dict(
        owner_id=OWNER,
        purchase_id=purchase_id,
        purchase_version=purchase_version,
        quote_id="quote-00000001",
        quote_version=version,
        seller_id="demo-seller-01",
        source_merchant_id="merchant-b",
        mode=Mode.LIVE,
        lines=lines,
        charges=charges,
        currency=Currency.INR,
        delivery="standard",
        expires_at=window.expires_at,
    )
    return CheckoutQuote(
        quote_id="quote-00000001",
        purchase_id=purchase_id,
        owner_id=OWNER,
        purchase_version=purchase_version,
        quote_version=version,
        demo_seller_id="demo-seller-01",
        source_merchant_id="merchant-b",
        mode=Mode.LIVE,
        lines=lines,
        charges=charges,
        total=Money.paise(59_000),
        currency=Currency.INR,
        delivery="standard",
        issued_at=issued_at,
        expires_at=window.expires_at,
        quote_hash=build_quote_hash(**terms),
    )


class World:
    """A ready-to-approve situation: purchase stored, quote stored, clock fixed."""

    def __init__(self, *, policy: PolicyPort | None = None) -> None:
        self.store = MemoryStore()
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds()
        self.uc = PurchaseUseCases(
            store=self.store,
            clock=self.clock,
            ids=self.ids,
            policy=policy or AllowAllPolicy(),
        )
        self.purchase_id = "purchase-0001"
        self.purchase = Purchase(
            purchase_id=self.purchase_id,
            owner_id=OWNER,
            basket_id="basket-0001",
            intent_revision=1,
            mode=Mode.LIVE,
        )
        self.quote = a_quote(self.purchase_id)
        self.store.seed(purchase_key(self.purchase_id), self.purchase)
        self.store.seed(quote_key(self.purchase_id, self.quote.quote_id), self.quote)

    def approve(
        self, *, idem: str = "idem-1", version: int = 1, **over: Any
    ) -> AttemptCreated | DomainError:
        args: dict[str, Any] = dict(
            owner_id=OWNER,
            purchase_id=self.purchase_id,
            quote_id=self.quote.quote_id,
            quote_hash=self.quote.quote_hash,
            quote_version=self.quote.quote_version,
            expected_purchase_version=version,
            idempotency=idem,
        )
        args.update(over)
        return self.uc.approve(**args)

    def approve_ok(self, *, idem: str = "idem-1", version: int = 1, **over: Any) -> AttemptCreated:
        """Approve, asserting an attempt was created. For tests about the attempt."""
        result = self.approve(idem=idem, version=version, **over)
        assert isinstance(result, AttemptCreated), f"approve failed: {result}"
        return result

    def purchase_row(self) -> Purchase:
        found = read(self.store, purchase_key(self.purchase_id), Purchase)
        assert found is not None, "the purchase should exist"
        return found

    def attempt_row(self, attempt_id: str) -> Attempt:
        found = read(self.store, attempt_key(self.purchase_id, attempt_id), Attempt)
        assert found is not None, "the attempt should exist"
        return found

    def attempts(self) -> int:
        return len([k for k in self.store.keys_matching("PURCHASE#") if "ATTEMPT#" in k[1]])

    def lookups(self) -> int:
        return self.store.count_matching("PROVIDER#")


def _attempt_for(world: World, consent_id: str) -> tuple[Attempt, ProviderLookup]:
    """The attempt and lookup this world's approval would create."""
    from services.domain.purchase import Approval, build_attempt_and_lookup
    from services.domain.transitions import ApprovalState

    approval = Approval(
        approval_id=consent_id,
        quote_id=world.quote.quote_id,
        quote_hash=world.quote.quote_hash,
        quote_version=1,
        purchase_version=1,
        owner_id=OWNER,
        status=ApprovalState.CONSUMED,
        consumed_attempt_id="attempt-00000001",
    )
    return build_attempt_and_lookup(
        attempt_id="attempt-00000001",
        purchase=world.purchase,
        approval=approval,
        quote=world.quote,
        provider="sim",
    )


# -- the happy path --------------------------------------------------------


def test_one_approval_creates_one_attempt_and_one_lookup() -> None:
    world = World()
    result = world.approve()
    assert isinstance(result, AttemptCreated)
    assert world.attempts() == 1
    assert world.lookups() == 1


def test_the_purchase_is_claimed_and_names_its_attempt() -> None:
    world = World()
    result = world.approve_ok()
    purchase = world.purchase_row()
    assert purchase.claim is ClaimState.CLAIMED
    assert purchase.active_attempt_id == result.attempt_id
    assert purchase.payment is PaymentState.CLAIMED
    assert purchase.version == 2


def test_the_attempt_starts_ready_with_the_payload_frozen() -> None:
    world = World()
    result = world.approve_ok()
    attempt = world.attempt_row(result.attempt_id)
    assert attempt.dispatch is DispatchState.READY
    assert attempt.started_at is None
    assert attempt.request_hash  # frozen now; WP-09 re-asserts it before sending


def test_all_eight_writes_commit_together() -> None:
    world = World()
    world.approve()
    assert world.store.commits == 1
    assert len(world.store.transactions[0]) == 8


# -- validation order ------------------------------------------------------


def test_a_stale_purchase_version_is_refused() -> None:
    result = World().approve(version=99)
    assert isinstance(result, VersionConflict)


def test_a_tampered_quote_hash_is_refused() -> None:
    result = World().approve(quote_hash="f" * 64)
    assert isinstance(result, QuoteHashMismatch)


def test_an_expired_quote_cannot_be_approved() -> None:
    world = World()
    world.clock.advance(121)
    assert isinstance(world.approve(), QuoteExpired)


def test_version_is_checked_before_expiry_so_the_error_is_deterministic() -> None:
    """Two failures apply at once; which one P1 shows must not be a coin toss."""
    world = World()
    world.clock.advance(121)
    assert isinstance(world.approve(version=99), VersionConflict)


def test_another_owner_gets_not_found_never_forbidden() -> None:
    world = World()
    result = world.approve(owner_id="owner-9999")
    assert isinstance(result, NotFound)


def test_policy_denial_also_conceals_as_not_found() -> None:
    world = World(policy=DenyPolicy(Action.APPROVE_PURCHASE))
    assert isinstance(world.approve(), NotFound)


def test_nothing_is_written_when_validation_fails() -> None:
    world = World()
    world.approve(quote_hash="f" * 64)
    assert world.store.commits == 0
    assert world.attempts() == 0


# -- idempotency -----------------------------------------------------------


def test_the_same_key_and_payload_replays_the_same_attempt() -> None:
    world = World()
    first = world.approve_ok(idem="idem-1")
    second = world.approve(idem="idem-1")
    assert isinstance(second, AttemptCreated)
    assert second.attempt_id == first.attempt_id
    assert second.replayed is True
    assert world.attempts() == 1


def test_the_same_key_with_a_different_payload_is_refused() -> None:
    world = World()
    world.approve(idem="idem-1")
    world.store.seed(
        idempotency_key(OWNER, "approve", "idem-2"),
        IdempotencyRecord(request_hash="different", result_ref="attempt-00000001"),
    )
    assert isinstance(world.approve(idem="idem-2"), IdempotencyPayloadMismatch)


def test_a_fresh_key_on_already_consented_terms_still_returns_one_attempt() -> None:
    """The shopper's client generated a new key; the consent is unchanged."""
    world = World()
    first = world.approve_ok(idem="idem-1")
    second = world.approve(idem="idem-2", version=2)
    assert isinstance(second, AttemptCreated)
    assert second.attempt_id == first.attempt_id
    assert world.attempts() == 1


def test_twenty_replays_produce_one_attempt() -> None:
    world = World()
    for _ in range(20):
        world.approve(idem="idem-1")
    assert world.attempts() == 1
    assert world.lookups() == 1


# -- concurrency: the claim the whole package exists to support -------------


def test_two_concurrent_approvals_create_exactly_one_attempt() -> None:
    """Both callers read, then both try to commit. Only one can win."""
    world = World()
    losers = []

    def second_caller(_writes: object) -> None:
        losers.append(world.approve(idem="idem-2"))

    world.store.before_transact = second_caller
    first = world.approve_ok(idem="idem-1")

    assert world.attempts() == 1
    assert world.lookups() == 1
    outcomes = [first, *losers]
    created = [o for o in outcomes if isinstance(o, AttemptCreated)]
    assert created, "somebody must have succeeded"
    assert len({o.attempt_id for o in created}) == 1


def test_the_loser_of_an_approval_race_is_told_about_the_real_attempt() -> None:
    """Never an error: their payment may be in flight, so 'failed' would lie.

    Which caller wins depends on interleaving -- the inner one commits first
    here -- so the assertion is deliberately order-agnostic: exactly one creates
    the attempt, the other is handed that same attempt marked as a replay.
    """
    world = World()
    inner = []

    def second_caller(_writes: object) -> None:
        inner.append(world.approve(idem="idem-2"))

    world.store.before_transact = second_caller
    outer = world.approve(idem="idem-1")

    outcomes = [outer, *inner]
    created = [o for o in outcomes if isinstance(o, AttemptCreated)]
    assert len(created) == len(outcomes), f"an approval errored: {outcomes}"

    creators = [o for o in created if not o.replayed]
    replays = [o for o in created if o.replayed]
    assert len(creators) == 1, "exactly one caller creates the attempt"
    assert len(replays) == 1, "the other is told about it, not given an error"
    assert replays[0].attempt_id == creators[0].attempt_id
    assert world.attempts() == 1


def test_approve_and_cancel_produce_exactly_one_effect() -> None:
    world = World()
    cancels = []

    def cancel_mid_flight(_writes: object) -> None:
        cancels.append(
            world.uc.cancel(
                owner_id=OWNER, purchase_id=world.purchase_id, expected_purchase_version=1
            )
        )

    world.store.before_transact = cancel_mid_flight
    approval = world.approve()

    approved = isinstance(approval, AttemptCreated) and not approval.replayed
    cancelled = isinstance(cancels[0], PurchaseCancelled)
    assert approved != cancelled, "exactly one of approve/cancel must take effect"
    if approved:
        assert world.attempts() == 1
    else:
        assert world.attempts() == 0


def test_cancel_and_approve_in_the_other_order_also_yield_one_effect() -> None:
    world = World()
    approvals = []

    def approve_mid_flight(_writes: object) -> None:
        approvals.append(world.approve())

    world.store.before_transact = approve_mid_flight
    cancellation = world.uc.cancel(
        owner_id=OWNER, purchase_id=world.purchase_id, expected_purchase_version=1
    )

    cancelled = isinstance(cancellation, PurchaseCancelled)
    approved = isinstance(approvals[0], AttemptCreated)
    assert cancelled != approved


def test_a_failed_guard_leaves_no_partial_state() -> None:
    """All-or-none: one rejected write means none of the eight are applied.

    Simulated by pre-seeding the provider-lookup row -- the same condition a
    real duplicate would trip -- and checking that no attempt, job, outbox event
    or evidence record survives.
    """
    world = World()
    consent = derive_approval_id(
        quote_id=world.quote.quote_id, quote_hash=world.quote.quote_hash, quote_version=1
    )
    attempt, lookup = _attempt_for(world, consent)
    world.store.seed(provider_lookup_key(attempt.payment_key), lookup)

    before = world.store.snapshot()
    result = world.approve()

    assert isinstance(result, ConditionFailed)
    assert "uniqueness" in result.reason
    assert world.attempts() == 0
    assert world.store.commits == 0
    # Nothing at all changed except the row we seeded ourselves.
    assert set(world.store.snapshot()) == set(before)


def test_an_unexpected_record_where_consent_belongs_is_refused() -> None:
    """We cannot tell whether money already moved, so we refuse rather than guess."""
    from services.domain.errors import InvalidRecord

    world = World()
    world.store.seed(
        approval_key(
            world.purchase_id,
            derive_approval_id(
                quote_id=world.quote.quote_id, quote_hash=world.quote.quote_hash, quote_version=1
            ),
        ),
        object(),
    )
    assert isinstance(world.approve(), InvalidRecord)
    assert world.attempts() == 0


# -- cancel ----------------------------------------------------------------


def test_cancel_before_any_claim_succeeds() -> None:
    world = World()
    result = world.uc.cancel(
        owner_id=OWNER, purchase_id=world.purchase_id, expected_purchase_version=1
    )
    assert isinstance(result, PurchaseCancelled)


def test_cancel_after_a_claim_is_refused() -> None:
    """There is an attempt; we cannot know if a provider call is in flight."""
    world = World()
    world.approve()
    result = world.uc.cancel(
        owner_id=OWNER, purchase_id=world.purchase_id, expected_purchase_version=2
    )
    assert isinstance(result, PurchaseAlreadyClaimed)


# -- expired before dispatch -----------------------------------------------


def test_expiring_an_unsent_attempt_releases_the_claim() -> None:
    world = World()
    created = world.approve_ok()
    expired = world.uc.expire_unsent(purchase_id=world.purchase_id, attempt_id=created.attempt_id)
    assert not isinstance(expired, DomainError), f"expire_unsent failed: {expired}"
    assert expired.dispatch is DispatchState.EXPIRED_UNSENT

    purchase = world.purchase_row()
    assert purchase.claim is ClaimState.RELEASED
    assert purchase.active_attempt_id is None
    assert purchase.payment is PaymentState.NOT_STARTED


def test_the_spent_payment_key_is_never_deleted() -> None:
    """A fresh approval means a new quote, so a new key. The old row stays."""
    world = World()
    created = world.approve_ok()
    world.uc.expire_unsent(purchase_id=world.purchase_id, attempt_id=created.attempt_id)
    assert world.lookups() == 1


def test_a_fresh_approval_after_expiry_gets_a_different_payment_key() -> None:
    world = World()
    first = world.approve_ok()
    world.uc.expire_unsent(purchase_id=world.purchase_id, attempt_id=first.attempt_id)

    world.clock.advance(200)
    later = a_quote(world.purchase_id, issued_at=world.clock.now(), version=2, purchase_version=3)
    world.store.seed(quote_key(world.purchase_id, later.quote_id), later)

    second = world.approve(idem="idem-2", version=3, quote_hash=later.quote_hash, quote_version=2)
    assert isinstance(second, AttemptCreated)
    assert second.payment_key != first.payment_key
    assert world.lookups() == 2


def test_expiry_loses_to_a_dispatch_that_already_started() -> None:
    """Once a provider has been called, only facts decide -- never expiry."""
    world = World()
    created = world.approve_ok()
    started = world.attempt_row(created.attempt_id)
    world.store.seed(
        attempt_key(world.purchase_id, created.attempt_id),
        started.model_copy(
            update={"dispatch": DispatchState.STARTED, "started_at": world.clock.now()}
        ),
    )
    result = world.uc.expire_unsent(purchase_id=world.purchase_id, attempt_id=created.attempt_id)
    assert not hasattr(result, "dispatch") or result.dispatch is not (DispatchState.EXPIRED_UNSENT)


# -- one active purchase per basket (D-6) ----------------------------------


def test_two_creates_for_one_basket_return_the_same_purchase() -> None:
    """Different idempotency keys would otherwise give two payable purchases."""
    store, clock, ids = MemoryStore(), FixedClock(NOW), SequentialIds()
    uc = PurchaseUseCases(store=store, clock=clock, ids=ids, policy=AllowAllPolicy())
    basket = a_basket()

    first = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-1"
    )
    second = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-2"
    )
    assert isinstance(first, PurchaseCreated) and isinstance(second, PurchaseCreated)
    assert second.purchase_id == first.purchase_id
    assert second.already_existed is True


def test_a_concurrent_create_also_collapses_to_one_purchase() -> None:
    store, clock, ids = MemoryStore(), FixedClock(NOW), SequentialIds()
    uc = PurchaseUseCases(store=store, clock=clock, ids=ids, policy=AllowAllPolicy())
    basket = a_basket()
    others = []

    def racer(_writes: object) -> None:
        others.append(
            uc.create_purchase(
                owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-2"
            )
        )

    store.before_transact = racer
    first = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-1"
    )
    ids_seen = {r.purchase_id for r in [first, *others] if isinstance(r, PurchaseCreated)}
    assert len(ids_seen) == 1


def test_cancelling_releases_the_basket_for_a_new_purchase() -> None:
    store, clock, ids = MemoryStore(), FixedClock(NOW), SequentialIds()
    uc = PurchaseUseCases(store=store, clock=clock, ids=ids, policy=AllowAllPolicy())
    basket = a_basket()
    created = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-1"
    )
    assert isinstance(created, PurchaseCreated)
    uc.cancel(owner_id=OWNER, purchase_id=created.purchase_id, expected_purchase_version=1)
    assert store.get(active_basket_key(basket.basket_id)) is None


# -- the approve control's enabled state -----------------------------------


def test_approve_enabled_is_computed_on_the_server() -> None:
    world = World()
    assert world.uc.approve_enabled(purchase=world.purchase, quote=world.quote) is True


def test_approve_enabled_goes_false_once_the_quote_expires() -> None:
    world = World()
    world.clock.advance(121)
    assert world.uc.approve_enabled(purchase=world.purchase, quote=world.quote) is False


def test_approve_enabled_is_false_with_no_quote() -> None:
    world = World()
    assert world.uc.approve_enabled(purchase=world.purchase, quote=None) is False


def test_approve_enabled_is_false_while_a_payment_is_unresolved() -> None:
    world = World()
    world.approve()
    purchase = world.purchase_row()
    unresolved = purchase.model_copy(update={"payment": PaymentState.UNKNOWN})
    assert world.uc.approve_enabled(purchase=unresolved, quote=world.quote) is False


# -- preparation and acceptance --------------------------------------------


# -- the counter invariant -------------------------------------------------


def test_approvals_committed_always_equals_attempts_created() -> None:
    """Asserted by test rather than watched during the demo."""
    world = World()
    for n in range(5):
        world.approve(idem=f"idem-{n}")
    assert world.attempts() == world.lookups() == 1


# -- regressions from the WP-08 implementation review -----------------------


def test_the_purchase_remembers_its_last_attempt() -> None:
    """R1: exposure used to be inferred from payment state with an invented id."""
    world = World()
    created = world.approve_ok()
    purchase = world.purchase_row()
    assert purchase.last_attempt_id == created.attempt_id


def test_the_last_attempt_survives_being_deactivated() -> None:
    world = World()
    created = world.approve_ok()
    world.uc.expire_unsent(purchase_id=world.purchase_id, attempt_id=created.attempt_id)
    purchase = world.purchase_row()
    assert purchase.active_attempt_id is None
    assert purchase.last_attempt_id == created.attempt_id


def test_the_exposure_snapshot_reads_real_attempts_only() -> None:
    """No fabricated ids, no assumed dispatch state."""
    world = World()
    created = world.approve_ok()
    snapshot = world.uc._snapshot(world.purchase_row())
    assert snapshot.active_attempt is not None and snapshot.last_attempt is not None
    assert snapshot.active_attempt.attempt_id == created.attempt_id
    assert snapshot.last_attempt.attempt_id == created.attempt_id
    assert snapshot.active_attempt.dispatch is DispatchState.READY


def test_a_purchase_with_no_attempts_has_an_empty_snapshot() -> None:
    world = World()
    snapshot = world.uc._snapshot(world.purchase)
    assert snapshot.active_attempt is None
    assert snapshot.last_attempt is None


def test_replaying_a_create_returns_the_original_purchase_and_job() -> None:
    """R2: the idempotency record was written but never read."""
    store, clock, ids = MemoryStore(), FixedClock(NOW), SequentialIds()
    uc = PurchaseUseCases(store=store, clock=clock, ids=ids, policy=AllowAllPolicy())
    basket = a_basket()

    first = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-1"
    )
    assert isinstance(first, PurchaseCreated)
    uc.cancel(owner_id=OWNER, purchase_id=first.purchase_id, expected_purchase_version=1)

    # The basket row is released, so only the idempotency record can answer.
    replay = uc.create_purchase(
        owner_id=OWNER, basket=basket, intent_revision=1, idempotency="idem-1"
    )
    assert isinstance(replay, PurchaseCreated)
    assert replay.purchase_id == first.purchase_id
    assert replay.job_id == first.job_id
    assert replay.already_existed is True


def test_a_replayed_approval_still_hands_back_a_job_to_poll() -> None:
    """R3: replays used to return an empty job id, which failed validation."""
    world = World()
    first = world.approve_ok(idem="idem-1")
    replay = world.approve_ok(idem="idem-1")
    assert replay.job_id == first.job_id
    assert replay.replayed is True
