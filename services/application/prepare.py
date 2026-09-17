"""Preparation: re-check the chosen basket, and build the exact quote (WP-08).

The half of WP-08 that comes before consent. A shopper picked a basket from a
comparison that may be minutes old; this re-asks the merchant, shows exactly
what changed, and only then freezes a quote.

One rule here matters more than the rest, and it is the tempting shortcut:
**when a refresh fails, the old price is never reused.** That line becomes
unknown, which makes the total unknown, which blocks the quote. Substituting the
stale figure from the original search would produce a confident, exact-looking
number that nobody has verified -- the single most dishonest thing this package
could do.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from services.application.ports import (
    MerchantPort,
)
from services.domain.basket import Basket, BasketLine
from services.domain.errors import DomainError, QuoteNotConstructible
from services.domain.ids import Id, Mode, Record, Timestamped
from services.domain.keys import quote_hash as build_quote_hash
from services.domain.money import (
    Amount,
    Charge,
    Currency,
    Money,
    Totals,
    compute_totals,
)
from services.domain.purchase import (
    Change,
    ChangeKind,
    CheckoutQuote,
    Diff,
    Preparation,
    Purchase,
    QuoteLine,
    build_diff,
    can_build_quote,
    quote_window,
)

#: SPEC section 9: 45 seconds per item fetch.
REFRESH_DEADLINE_SECONDS = 45

#: The simulated seller every quote names. Real merchants are never the seller:
#: nothing here places an order with them.
DEMO_SELLER_ID = "demo-seller-01"


class RefreshedLine(Record):
    """One line as it stands after the re-check.

    ``line_total`` is an ``Amount``, not a ``Money``, precisely so that a line we
    could not price is representable as unknown rather than as a stale number.
    """

    item_id: Id
    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    quantity_base: int = Field(gt=0)
    dimension: str = Field(min_length=1, max_length=16)
    unit_price: Money | None
    line_total: Amount
    in_stock: bool = True
    substituted: bool = False
    pack_changed: bool = False
    #: The pack size the merchant is selling now, so a pack change can say what
    #: it changed to rather than repeating the quantity on both sides.
    pack_base_units: int | None = None
    failure_code: str | None = None


class RefreshedFacts(Timestamped):
    """Everything the re-check learned, kept so the quote is built from it."""

    purchase_id: Id
    merchant_id: str = Field(min_length=1, max_length=64)
    mode: Mode
    location: str = Field(min_length=1, max_length=200)
    delivery: str = Field(min_length=1, max_length=120)
    lines: tuple[RefreshedLine, ...] = Field(min_length=1)
    charges: tuple[Charge, ...] = ()
    refreshed_at: datetime

    def totals(self) -> Totals:
        return compute_totals([line.line_total for line in self.lines], list(self.charges))


def refresh_line(
    merchant: MerchantPort,
    *,
    line: BasketLine,
    location: str,
    deadline_seconds: int = REFRESH_DEADLINE_SECONDS,
) -> RefreshedLine:
    """Re-ask the merchant about one line.

    Every failure path lands in the same place: an unknown amount. A timeout, a
    blocked page, an out-of-stock result and a missing price are different
    stories, but none of them is a reason to quote the old number.
    """
    observed = merchant.refresh(location, line.sku, deadline_seconds)

    if isinstance(observed, DomainError):
        return RefreshedLine(
            item_id=line.item_id,
            sku=line.sku,
            name=line.name,
            quantity_base=line.selected_base_units,
            dimension=line.dimension,
            unit_price=None,
            line_total=Amount.unknown(),
            failure_code=observed.code,
        )

    if not observed.in_stock:
        return RefreshedLine(
            item_id=line.item_id,
            sku=line.sku,
            name=observed.name,
            quantity_base=line.selected_base_units,
            dimension=observed.pack.dimension.value,
            unit_price=observed.price,
            line_total=Amount.unknown(),
            in_stock=False,
            failure_code="out_of_stock",
        )

    if observed.pack.value_base != line.pack_base_units:
        # The merchant changed the pack size. Re-selecting packs is WP-06's job,
        # not preparation's, so we refuse to price it rather than multiplying the
        # old pack count by the new pack's price -- which would quote five kilos
        # at the cost of one.
        return RefreshedLine(
            item_id=line.item_id,
            sku=observed.sku,
            name=observed.name,
            quantity_base=line.selected_base_units,
            dimension=observed.pack.dimension.value,
            unit_price=observed.price,
            line_total=Amount.unknown(),
            pack_changed=True,
            pack_base_units=observed.pack.value_base,
            failure_code="pack_size_changed",
        )

    packs = line.selected_base_units // line.pack_base_units
    return RefreshedLine(
        item_id=line.item_id,
        sku=observed.sku,
        name=observed.name,
        quantity_base=line.selected_base_units,
        dimension=observed.pack.dimension.value,
        unit_price=observed.price,
        line_total=Amount.known(observed.price.times(packs)),
        substituted=observed.sku != line.sku,
    )


def diff_between(basket: Basket, facts: RefreshedFacts) -> Diff:
    """What changed between what the shopper was shown and what is true now.

    Pure: the same basket and facts always produce the same change list, and
    therefore the same hash, which is what makes acceptance-by-hash meaningful.
    """
    changes: list[Change] = []
    by_item = {line.item_id: line for line in basket.lines}

    for refreshed in facts.lines:
        original = by_item.get(refreshed.item_id)
        if original is None:
            continue

        if not refreshed.in_stock:
            changes.append(
                Change(
                    kind=ChangeKind.AVAILABILITY,
                    target=refreshed.sku,
                    before="in_stock",
                    after="out_of_stock",
                )
            )
            continue

        if refreshed.pack_changed:
            changes.append(
                Change(
                    kind=ChangeKind.PACK,
                    target=refreshed.sku,
                    before=str(original.pack_base_units),
                    after=str(refreshed.pack_base_units),
                )
            )
            continue

        if refreshed.line_total.amount is None:
            changes.append(
                Change(
                    kind=ChangeKind.PRICE,
                    target=refreshed.sku,
                    before=str(original.line_total.amount.amount_paise)
                    if original.line_total.amount
                    else "unknown",
                    after="unknown",
                )
            )
            continue

        was = original.line_total.amount
        now = refreshed.line_total.amount
        if was is not None and was.amount_paise != now.amount_paise:
            changes.append(
                Change(
                    kind=ChangeKind.PRICE,
                    target=refreshed.sku,
                    before=str(was.amount_paise),
                    after=str(now.amount_paise),
                )
            )

        if refreshed.substituted:
            changes.append(
                Change(
                    kind=ChangeKind.PACK,
                    target=original.sku,
                    before=original.sku,
                    after=refreshed.sku,
                )
            )

    changes.extend(_fee_changes(basket, facts))
    # Order the changes so the hash does not depend on how we happened to walk.
    changes.sort(key=lambda c: (c.kind.value, c.target, c.before, c.after))
    return build_diff(changes)


def _fee_changes(basket: Basket, facts: RefreshedFacts) -> list[Change]:
    before = {c.kind: c for c in (basket.fee_assessment.charges if basket.fee_assessment else ())}
    after = {c.kind: c for c in facts.charges}
    changes: list[Change] = []
    for kind in sorted(set(before) | set(after), key=lambda k: k.value):
        old, new = before.get(kind), after.get(kind)
        old_value = "absent" if old is None else _charge_text(old)
        new_value = "absent" if new is None else _charge_text(new)
        if old_value != new_value:
            changes.append(
                Change(kind=ChangeKind.FEE, target=kind.value, before=old_value, after=new_value)
            )
    return changes


def _charge_text(charge: Charge) -> str:
    return "unknown" if charge.amount is None else str(charge.amount.amount_paise)


def build_quote(
    *,
    purchase: Purchase,
    preparation: Preparation,
    facts: RefreshedFacts,
    quote_id: str,
    quote_version: int,
    now: datetime,
) -> CheckoutQuote | DomainError:
    """Freeze an exact, hash-bound offer -- or refuse and say why.

    ``can_build_quote`` is the gate: an unknown or estimated charge, an unaccepted
    diff, or a stale preparation each block it. That is deliberately stricter than
    comparison, where an estimated total is perfectly legitimate. The control says
    "Approve simulated Rs X"; X has to be a number we actually know.
    """
    totals = facts.totals()
    refusal = can_build_quote(preparation, totals, now)
    if refusal is not None:
        return refusal
    total = totals.total
    if total is None:  # implied by can_build_quote; stated so the types agree
        return QuoteNotConstructible(reason="unknown_charge", charge_kinds=())

    unpriced = [
        line.sku
        for line in facts.lines
        if line.unit_price is None or line.line_total.amount is None
    ]
    if unpriced:
        # Unreachable while can_build_quote refuses unknown totals, and asserted
        # anyway: relying on another rule to keep a None out of a quote is the
        # kind of coupling that survives right up until someone edits that rule.
        return QuoteNotConstructible(reason="unpriced_line", charge_kinds=())

    priced: list[QuoteLine] = []
    for line in facts.lines:
        # Both were checked above; binding them locally lets the type checker
        # see it too, rather than trusting a guard it cannot follow.
        unit_price, line_total = line.unit_price, line.line_total.amount
        if unit_price is None or line_total is None:
            return QuoteNotConstructible(reason="unpriced_line", charge_kinds=())
        priced.append(
            QuoteLine(
                sku=line.sku,
                name=line.name,
                quantity_base=line.quantity_base,
                dimension=line.dimension,
                unit_price=unit_price,
                line_total=line_total,
                substituted=line.substituted,
            )
        )
    lines = tuple(priced)
    window = quote_window(now)
    digest_value = build_quote_hash(
        owner_id=purchase.owner_id,
        purchase_id=purchase.purchase_id,
        purchase_version=purchase.version,
        quote_id=quote_id,
        quote_version=quote_version,
        seller_id=DEMO_SELLER_ID,
        source_merchant_id=facts.merchant_id,
        mode=facts.mode,
        lines=lines,
        charges=facts.charges,
        currency=Currency.INR,
        delivery=facts.delivery,
        expires_at=window.expires_at,
    )
    return CheckoutQuote(
        quote_id=quote_id,
        purchase_id=purchase.purchase_id,
        owner_id=purchase.owner_id,
        purchase_version=purchase.version,
        quote_version=quote_version,
        demo_seller_id=DEMO_SELLER_ID,
        source_merchant_id=facts.merchant_id,
        mode=facts.mode,
        lines=lines,
        charges=facts.charges,
        total=total,
        currency=Currency.INR,
        delivery=facts.delivery,
        issued_at=window.issued_at,
        expires_at=window.expires_at,
        quote_hash=digest_value,
    )


__all__ = [
    "DEMO_SELLER_ID",
    "REFRESH_DEADLINE_SECONDS",
    "RefreshedFacts",
    "RefreshedLine",
    "build_quote",
    "diff_between",
    "refresh_line",
]
