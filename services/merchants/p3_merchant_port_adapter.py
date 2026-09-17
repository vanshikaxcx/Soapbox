"""Adapter: our `Merchant` port -> P3's `MerchantPort` Protocol (WP-08).

Why this exists: P3's WP-08 depends on a `MerchantPort` with a different
shape than the `Merchant` port WP-04 actually built (compared directly
against P3's `services/application/ports.py` on `origin/p3`):

    P3 expects:
        def refresh(self, location: str, sku: str, deadline_seconds: int)
            -> Observation | DomainError
        def assess_fees(self, location: str, merchant_id: str, line_hash: str,
                         deadline_seconds: int) -> tuple[Charge, ...] | DomainError

    WP-04 built:
        def refresh(self, location: Location, sku: str, deadline: datetime)
            -> Observation | MerchantError
        def assess_fees(self, location: Location, exact_lines: list[Line], deadline: datetime)
            -> FeeAssessment | None

    Different `location` type, different deadline representation, different
    Observation/error/fee types entirely (P3's live in `services.domain`,
    ours in `services.merchants.models`) — plus their own `Observation`,
    `DomainError` and `Charge` classes, not ours.

Verified for real as of the merge into feat/wp-06-search-comparison-p2
(P3's feat/wp-02-08-09-transaction-safety-p3, itself rebuilt on P4's WP-00
baseline, merged cleanly — no conflicts, both sides touch disjoint files):
`isinstance(P3MerchantPortAdapter(...), MerchantPort)` is `True`, and
`refresh()` against real live Blinkit data returns a correctly-typed
`services.domain.catalog.Observation` with correct unit conversion
(5kg -> 5000g base units), Money, and Mode. This was previously only
checked against hand-written stubs before the repo layouts merged; it's
now checked against the real thing.

Three real assumptions below are NOT settled facts — they need P3 to
confirm, not just this file's opinion:

1. **What the `location: str` parameter actually contains.** P3's Protocol
   takes a bare string with no documented format. This adapter assumes it's
   the pincode and nothing else (`Location(locality="", pincode=location)`).
   If P3 means a composite key, an opaque location_id, or a "locality,
   pincode" string, every call here would silently look up the wrong
   locality without ever raising — the dangerous kind of wrong.
2. **There is no merchant-fetch-failure DomainError.** P3's error taxonomy
   (`services/domain/errors.py`, confirmed by reading its `__all__`) has no
   equivalent of TIMEOUT/CAPTCHA/BLOCKED/LOCATION_UNSUPPORTED/LAYOUT_CHANGED.
   Those are P2's failure modes, not domain rules, so it makes sense P3
   never defined them — but something has to represent them on P3's side.
   This adapter uses `InvalidRecord(record="merchant_fetch", detail=...)` as
   a stand-in, encoding our real MerchantErrorCode in `detail`. That's a
   workaround, not a real fix: WP-02 explicitly reserves adding to its
   error union as "a deliberate act" (see errors.py's module docstring), so
   this needs a real decision from P3, not a unilateral addition here.
3. **`assess_fees` cannot be a pure translation.** P3's signature takes a
   `line_hash`, not the actual line items — so the only way to compute a
   real fee is to already know which lines that hash refers to, which is
   state P3/P4 own (presumably via WP-07's store), not something WP-04 has
   access to. This adapter takes an explicit `line_lookup` callback rather
   than silently fabricating an answer; if it's not wired up, or the hash
   is unrecognized, it returns a typed error instead of guessing.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# --- P3's types (services.domain / services.application on origin/p3) -----
# Not resolvable in this repo yet; see module docstring. Left as real,
# fetched-not-guessed import paths so this file is a drop-in once the repo
# layouts are reconciled.
from services.application.ports import MerchantPort  # noqa: F401  (structural target)
from services.domain.catalog import ExtractionStatus as P3ExtractionStatus
from services.domain.catalog import Observation as P3Observation
from services.domain.errors import DomainError, InvalidRecord
from services.domain.ids import Mode as P3Mode
from services.domain.money import Charge, ChargeKind, Confidence, Money
from services.domain.units import Quantity, Unit

from .base import Merchant
from .models import ExtractionStatus, Line, Location, MerchantError, Mode, Observation

# Our free-form unit strings (from parsing.parse_pack_size) -> P3's closed Unit enum.
# "pack"/"pcs" both collapse to PIECE: P3 doesn't distinguish pack-count from
# piece-count, and neither of our connectors currently emits true piece counts.
_UNIT_MAP: dict[str, Unit] = {
    "kg": Unit.KG,
    "g": Unit.G,
    "l": Unit.L,
    "ml": Unit.ML,
    "pack": Unit.PIECE,
    "pcs": Unit.PIECE,
}

_EXTRACTION_STATUS_MAP: dict[ExtractionStatus, P3ExtractionStatus] = {
    ExtractionStatus.OK: P3ExtractionStatus.OK,
    ExtractionStatus.PARTIAL: P3ExtractionStatus.PARTIAL,
    ExtractionStatus.BLOCKED: P3ExtractionStatus.BLOCKED,
    # P3 has no NOT_FOUND/ERROR equivalent; both collapse to FAILED.
    ExtractionStatus.NOT_FOUND: P3ExtractionStatus.FAILED,
    ExtractionStatus.ERROR: P3ExtractionStatus.FAILED,
}


def _observation_id(merchant_id: str, sku: str) -> str:
    """P3's `Id` type is pattern-constrained (`^[A-Za-z0-9_-]{8,64}$`).

    Our own SKUs aren't guaranteed to match it — Zepto's, for example, is a
    full path fragment ("pn/<slug>/pvid/<id>") containing slashes, which
    this pattern rejects outright. A stable hash of merchant+sku is always
    valid and always the same for the same (merchant, sku) pair.
    """
    return hashlib.sha256(f"{merchant_id}:{sku}".encode()).hexdigest()[:32]


def _to_p3_observation(obs: Observation) -> P3Observation:
    unit = _UNIT_MAP.get(obs.unit)
    if unit is None:
        raise ValueError(f"unmapped unit {obs.unit!r}; add it to _UNIT_MAP")
    return P3Observation(
        observation_id=_observation_id(obs.merchant, obs.sku),
        merchant_id=obs.merchant,
        sku=obs.sku,
        url=obs.url,
        name=obs.product_name,
        brand=None,  # not extracted by either connector today
        attributes={},  # hard-attribute extraction isn't built (WP-06 scope)
        pack=Quantity.of(int(obs.pack_size), unit),
        price=Money.paise(obs.price_paise),
        in_stock=obs.in_stock,
        verified_location=obs.verified_location.pincode,
        fetched_at=obs.fetch_time,
        evidence_key=obs.evidence_key,
        extraction_status=_EXTRACTION_STATUS_MAP[obs.extraction_status],
        mode=P3Mode.LIVE if obs.mode == Mode.LIVE else P3Mode.FIXTURE,
    )


def _to_domain_error(err: MerchantError) -> DomainError:
    # See module docstring, assumption 2: no dedicated merchant-error type
    # exists on P3's side yet. This is a labeled stand-in, not a real fix.
    return InvalidRecord(
        record="merchant_fetch",
        detail=f"{err.merchant}:{err.code.value}:{err.message}"[:200],
    )


class P3MerchantPortAdapter:
    """Wraps one WP-04 `Merchant` connector to satisfy P3's `MerchantPort`.

    `line_lookup`, if given, resolves a `line_hash` (as `assess_fees`
    receives it) back to the `Line`s it represents — required because P3's
    signature doesn't carry the lines themselves. See module docstring,
    assumption 3. Without it, `assess_fees` always returns a typed error
    rather than fabricating a number.
    """

    def __init__(
        self,
        merchant: Merchant,
        *,
        line_lookup: Callable[[str], list[Line] | None] | None = None,
    ) -> None:
        self._merchant = merchant
        self._line_lookup = line_lookup

    def refresh(
        self, location: str, sku: str, deadline_seconds: int
    ) -> P3Observation | DomainError:
        # Assumption 1 (module docstring): `location` is treated as a bare
        # pincode. Confirm with P3 before trusting this in production.
        our_location = Location(locality="", pincode=location)
        deadline = datetime.now(UTC) + timedelta(seconds=deadline_seconds)
        result = self._merchant.refresh(our_location, sku, deadline)
        if isinstance(result, MerchantError):
            return _to_domain_error(result)
        return _to_p3_observation(result)

    def assess_fees(
        self, location: str, merchant_id: str, line_hash: str, deadline_seconds: int
    ) -> tuple[Charge, ...] | DomainError:
        if self._line_lookup is None:
            return InvalidRecord(
                record="assess_fees",
                detail="no line_lookup configured; cannot resolve line_hash without WP-07's store",
            )
        lines = self._line_lookup(line_hash)
        if lines is None:
            return InvalidRecord(
                record="assess_fees", detail=f"unrecognized line_hash {line_hash!r}"
            )

        our_location = Location(locality="", pincode=location)
        deadline = datetime.now(UTC) + timedelta(seconds=deadline_seconds)
        assessment = self._merchant.assess_fees(our_location, lines, deadline)
        if assessment is None:
            return InvalidRecord(record="assess_fees", detail="merchant returned no assessment")

        confidence = Confidence.ESTIMATED if assessment.completeness == "estimated" else (
            Confidence.UNKNOWN if assessment.completeness == "unknown" else Confidence.VERIFIED
        )

        def charge(kind: ChargeKind, amount_paise: int | None) -> Charge | None:
            if amount_paise is None:
                return None
            if confidence is Confidence.UNKNOWN:
                return Charge.unknown_charge(kind)
            return Charge.known_charge(kind, Money.paise(amount_paise), confidence)

        charges = [
            c
            for c in (
                charge(ChargeKind.DELIVERY, assessment.delivery_fee_paise),
                charge(ChargeKind.OTHER, assessment.platform_fee_paise),
                charge(ChargeKind.HANDLING, assessment.other_fees_paise),
            )
            if c is not None
        ]
        return tuple(charges)
