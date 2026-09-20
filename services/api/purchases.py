"""Purchase and demo endpoints (WP-08, WP-09).

Every handler does the same four things and nothing else: check the request
shape, take ``owner_id`` from the validated token, call one use case, map the
result. No handler contains a rule.

``owner_id`` is a parameter here rather than something read from the body. The
caller -- P4's Lambda entry point -- derives it from the access token. A body that
carries an owner id is rejected outright: the browser does not get to say who it
is.
"""

from __future__ import annotations

from typing import Any

from services.api.responses import Response, accepted, failed, ok
from services.application.cases import CaseService
from services.application.checkout import CheckoutTask
from services.application.copy import (
    ESTIMATED_FEES_NOTE,
    FIXTURE_LABEL,
    SIMULATION_DISCLAIMER,
    approve_label,
    lower_bound_label,
)
from services.application.operator import OperatorUseCases
from services.application.purchase import PurchaseUseCases, quote_key
from services.application.reconcile import ReconcileTask
from services.domain.basket import Basket
from services.domain.errors import DomainError, InvalidRecord
from services.domain.ids import Mode
from services.domain.money import Confidence, Money
from services.domain.purchase import CheckoutQuote, Purchase

OWNER_IN_BODY = InvalidRecord(
    record="request", detail="owner_id must come from the token, never the body"
)


class PurchaseApi:
    """The HTTP surface WP-08 and WP-09 promise. P1 codes against this."""

    def __init__(
        self,
        *,
        use_cases: PurchaseUseCases,
        reconciler: ReconcileTask | None = None,
        cases: CaseService | None = None,
        # Any, not Scenario: this module imports the concrete Scenario enum
        # inside the one handler that needs it, so the simulator stays off the
        # API layer's module-level imports. The handler forwards the scenario
        # without inspecting it; the provider is what constrains the type.
        operator: OperatorUseCases[Any] | None = None,
        checkout: CheckoutTask | None = None,
    ) -> None:
        self._uc = use_cases
        self._reconciler = reconciler
        self._cases = cases
        self._operator = operator
        self._checkout = checkout

    # -- purchases ---------------------------------------------------------

    def create_purchase(
        self,
        *,
        owner_id: str,
        body: dict[str, Any],
        idempotency_key: str,
        request_id: str,
        basket: Basket,
    ) -> Response:
        guard = _reject_owner_in_body(body, request_id)
        if guard is not None:
            return guard

        result = self._uc.create_purchase(
            owner_id=owner_id,
            basket=basket,
            intent_revision=int(body["intent_revision"]),
            idempotency=idempotency_key,
        )
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return accepted(job_id=result.job_id, resource_id=result.purchase_id, request_id=request_id)

    def accept_preparation(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        version: int,
        body: dict[str, Any],
        request_id: str,
    ) -> Response:
        guard = _reject_owner_in_body(body, request_id)
        if guard is not None:
            return guard

        result = self._uc.accept_preparation(
            owner_id=owner_id,
            purchase_id=purchase_id,
            version=version,
            diff_hash=body["diff_hash"],
            expected_purchase_version=int(body["expected_purchase_version"]),
        )
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return ok(
            {
                "preparation_version": result.preparation_version,
                "quote": _quote_view(result.quote),
            },
            request_id,
        )

    def approve(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        body: dict[str, Any],
        idempotency_key: str,
        request_id: str,
    ) -> Response:
        """The only endpoint that turns consent into a payment attempt."""
        guard = _reject_owner_in_body(body, request_id)
        if guard is not None:
            return guard

        result = self._uc.approve(
            owner_id=owner_id,
            purchase_id=purchase_id,
            quote_id=body["quote_id"],
            quote_hash=body["quote_hash"],
            quote_version=int(body["quote_version"]),
            expected_purchase_version=int(body["expected_purchase_version"]),
            idempotency=idempotency_key,
        )
        if isinstance(result, DomainError):
            return failed(result, request_id)

        if result.replayed:
            # They asked for an attempt and there is one. That another call made
            # it is our bookkeeping, not their problem -- and calling this a
            # conflict would show "failed" to someone whose payment is in flight.
            return ok({"attempt_id": result.attempt_id, "replayed": True}, request_id)
        return accepted(job_id=result.job_id, resource_id=result.attempt_id, request_id=request_id)

    def cancel(
        self,
        *,
        owner_id: str,
        purchase_id: str,
        body: dict[str, Any],
        request_id: str,
    ) -> Response:
        result = self._uc.cancel(
            owner_id=owner_id,
            purchase_id=purchase_id,
            expected_purchase_version=int(body["expected_purchase_version"]),
        )
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return ok({"purchase_id": result.purchase_id, "version": result.version}, request_id)

    def reconcile(self, *, owner_id: str, purchase_id: str, request_id: str) -> Response:
        """Read the original references. Creates nothing."""
        if self._reconciler is None:
            return failed(
                InvalidRecord(record="server", detail="reconcile unavailable"), request_id
            )
        result = self._reconciler.run(owner_id=owner_id, purchase_id=purchase_id)
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return ok(result, request_id)

    def read_purchase(self, *, owner_id: str, purchase_id: str, request_id: str) -> Response:
        purchase = self._uc.read(owner_id=owner_id, purchase_id=purchase_id)
        if isinstance(purchase, DomainError):
            return failed(purchase, request_id)

        quote = self._current_quote(purchase)
        return ok(
            {
                "purchase_id": purchase.purchase_id,
                "version": purchase.version,
                "mode": str(purchase.mode),
                # Three separate facts. Never merged into one status line.
                "payment": str(purchase.payment),
                "order": str(purchase.order),
                "refund": str(purchase.refund),
                "active_attempt_id": purchase.active_attempt_id,
                "quote": _quote_view(quote) if quote else None,
                # Server-computed. P1 binds the approve control to THIS, never to a
                # countdown, or the button can re-enable in the gap between "looks
                # expired" and the expiry actually committing.
                "approve_enabled": self._uc.approve_enabled(purchase=purchase, quote=quote),
                "disclaimer": SIMULATION_DISCLAIMER,
                "fixture_label": FIXTURE_LABEL if purchase.mode is Mode.FIXTURE else None,
            },
            request_id,
        )

    def read_case(self, *, owner_id: str, purchase_id: str, request_id: str) -> Response:
        if self._cases is None:
            return failed(InvalidRecord(record="server", detail="cases unavailable"), request_id)
        case = self._cases.read_case(owner_id=owner_id, purchase_id=purchase_id)
        if isinstance(case, DomainError):
            return failed(case, request_id)
        return ok(
            {
                "case_id": case.case_id,
                "purchase_id": case.purchase_id,
                "status": str(case.status),
                "known_facts": [str(f) for f in case.known_facts],
                # Named gaps, not an absence. This is what the shopper reads.
                "missing_facts": [str(f) for f in case.missing_facts],
            },
            request_id,
        )

    # -- operator ----------------------------------------------------------

    def set_scenario(self, *, owner_id: str, body: dict[str, Any], request_id: str) -> Response:
        """Operator-only. A shopper receives 404, not 403."""
        if self._operator is None:
            return failed(InvalidRecord(record="server", detail="demo unavailable"), request_id)
        from services.simulator.ledger import Scenario

        result = self._operator.set_scenario(owner_id=owner_id, scenario=Scenario(body["scenario"]))
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return ok(result, request_id)

    def effect_counts(self, *, owner_id: str, request_id: str) -> Response:
        if self._operator is None:
            return failed(InvalidRecord(record="server", detail="demo unavailable"), request_id)
        result = self._operator.effect_counts(owner_id=owner_id)
        if isinstance(result, DomainError):
            return failed(result, request_id)
        return ok(result, request_id)

    # -- helpers -----------------------------------------------------------

    def _current_quote(self, purchase: Purchase) -> CheckoutQuote | None:
        for version in range(purchase.preparation_version, 0, -1):
            found = self._uc._store.get(quote_key(purchase.purchase_id, f"quote-{version:08d}"))
            if isinstance(found, CheckoutQuote):
                return found
        return None


def _money(amount: Money) -> dict[str, Any]:
    """The baseline's MoneyINR shape.

    Integer paise plus its currency, as one object, so an amount can never be
    read without the unit it is denominated in. The domain keeps paise as an
    int; this is the only place it is shaped for the wire.
    """
    return {"amount_paise": amount.amount_paise, "currency": str(amount.currency)}


def _quote_view(quote: CheckoutQuote) -> dict[str, Any]:
    """Everything shown, with nothing truncated behind a 'show more'."""
    return {
        "quote_id": quote.quote_id,
        "quote_version": quote.quote_version,
        "quote_hash": quote.quote_hash,
        "seller": quote.demo_seller_id,
        "source_merchant": quote.source_merchant_id,
        "mode": str(quote.mode),
        "lines": [
            {
                "sku": line.sku,
                "name": line.name,
                "quantity_base": line.quantity_base,
                "dimension": line.dimension,
                "unit_price": _money(line.unit_price),
                "line_total": _money(line.line_total),
                "substituted": line.substituted,
            }
            for line in quote.lines
        ],
        # An unknown charge omits `amount` entirely rather than sending null:
        # the AWS/SAM subset forbids `nullable`, and absent says "we could not
        # confirm this fee" without inviting it to be read as zero.
        "charges": [
            {"kind": str(c.kind), "confidence": str(c.confidence)}
            | ({"amount": _money(c.amount)} if c.amount is not None else {})
            for c in quote.charges
        ],
        "total": _money(quote.total),
        # Whether `total` is an exact price or a maximum. P1 needs this for
        # every surface that shows the amount, not just the approve control:
        # rendering a ceiling as if it were the expected price is the mistake
        # WP-02-A1 exists to prevent.
        "amount_is_ceiling": quote.total_confidence is Confidence.ESTIMATED,
        "delivery": quote.delivery,
        "expires_at": quote.expires_at.isoformat(),
        # The exact label. P1 renders it; P1 does not compose it.
        "approve_label": approve_label(quote.total.amount_paise, quote.total_confidence),
        "disclaimer": SIMULATION_DISCLAIMER,
        # Present only when the amount is a ceiling, so its presence is itself
        # the signal. A quote with exact fees has nothing to disclose here.
        **(
            {"estimated_fees_note": ESTIMATED_FEES_NOTE}
            if quote.total_confidence is Confidence.ESTIMATED
            else {}
        ),
    }


def _reject_owner_in_body(body: dict[str, Any], request_id: str) -> Response | None:
    if "owner_id" in body:
        return failed(OWNER_IN_BODY, request_id)
    return None


__all__ = ["PurchaseApi", "lower_bound_label"]
