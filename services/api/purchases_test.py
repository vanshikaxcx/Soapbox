"""The HTTP surface (WP-08, WP-09).

What is asserted here is the contract P1 codes against: status codes, the exact
shape of a body, and the fields the UI is required to bind to rather than derive.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from services.api.purchases import PurchaseApi
from services.api.responses import STATUS, Response, failed, ok, status_for
from services.application.cases import CaseService
from services.application.copy import SIMULATION_DISCLAIMER
from services.application.fakes import SequentialIds
from services.application.operator import OperatorUseCases
from services.application.prepare_test import OWNER, PURCHASE_ID, World, merchant_selling
from services.application.purchase import NotFound
from services.application.reconcile import ReconcileTask
from services.domain.errors import QuoteExpired, VersionConflict
from services.simulator.adapter import ReadOnlyProvider, SimulatorProvider
from services.simulator.ledger import Scenario
from services.simulator.operations import Simulator

OPERATOR = "operator-0001"
REQ = "request-0001"


class OperatorPolicy:
    def is_operator(self, owner_id: str) -> bool:
        return owner_id == OPERATOR


class Api:
    """A world driven to a live quote, with the HTTP surface on top of it."""

    def __init__(self, scenario: Scenario = Scenario.SUCCESS) -> None:
        self.world = World()
        _prep, self.diff = self.world.prepare_ok(merchant_selling(59_500))
        self.simulator = Simulator(clock=self.world.clock, ids=SequentialIds(), scenario=scenario)
        provider = SimulatorProvider(self.simulator)
        self.api = PurchaseApi(
            use_cases=self.world.uc,
            reconciler=ReconcileTask(
                store=self.world.store, clock=self.world.clock, provider=ReadOnlyProvider(provider)
            ),
            cases=CaseService(store=self.world.store, clock=self.world.clock, ids=SequentialIds()),
            operator=OperatorUseCases(
                store=self.world.store, simulator=self.simulator, policy=OperatorPolicy()
            ),
        )

    def version(self) -> int:
        return self.world.purchase_row().version

    def accept(self) -> Response:
        return self.api.accept_preparation(
            owner_id=OWNER,
            purchase_id=PURCHASE_ID,
            version=1,
            body={"diff_hash": self.diff.hash(), "expected_purchase_version": self.version()},
            request_id=REQ,
        )


# -- the envelope ----------------------------------------------------------


def test_success_bodies_carry_data_and_a_request_id() -> None:
    response = ok({"a": 1}, REQ)
    assert response.body == {"data": {"a": 1}, "request_id": REQ}


def test_error_bodies_carry_a_stable_code_and_no_prose() -> None:
    response = failed(VersionConflict(expected=1, actual=2), REQ)
    assert response.status == 409
    assert response.body["error"]["code"] == "version_conflict"
    assert response.body["error"]["details"] == {"expected": 1, "actual": 2}


def test_an_inaccessible_record_is_404_not_403() -> None:
    """Telling someone it exists but is not theirs still tells them."""
    assert status_for(NotFound("purchase")) == 404
    assert 403 not in STATUS.values()


def test_an_expiry_is_410() -> None:
    assert status_for(QuoteExpired(quote_id="q")) == 410


def test_an_unmapped_error_is_500_rather_than_a_guess() -> None:
    from services.domain.errors import DomainError

    class Invented(DomainError):
        pass

    assert status_for(Invented()) == 500


# -- the endpoints ---------------------------------------------------------


def test_accepting_a_preparation_returns_the_quote() -> None:
    api = Api()
    response = api.accept()
    assert response.status == 200
    quote = response.body["data"]["quote"]
    assert quote["total"] == {"amount_paise": 60_500, "currency": "INR"}
    assert quote["disclaimer"] == SIMULATION_DISCLAIMER


def test_the_quote_carries_the_exact_approve_label() -> None:
    """P1 renders this string. P1 does not compose it."""
    api = Api()
    quote = api.accept().body["data"]["quote"]
    assert quote["approve_label"] == "Approve simulated ₹605.00"


def test_an_exact_quote_is_not_flagged_as_a_ceiling() -> None:
    """The default must be the honest one: a ceiling is opt-in, never assumed."""
    api = Api()
    quote = api.accept().body["data"]["quote"]
    assert quote["amount_is_ceiling"] is False
    assert "up to" not in quote["approve_label"]


def test_approving_returns_202_with_a_job_to_poll() -> None:
    api = Api()
    quote = api.accept().body["data"]["quote"]
    response = api.api.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        body={
            "quote_id": quote["quote_id"],
            "quote_hash": quote["quote_hash"],
            "quote_version": quote["quote_version"],
            "expected_purchase_version": api.version(),
        },
        idempotency_key="idem-1",
        request_id=REQ,
    )
    assert response.status == 202
    assert response.body["data"]["resource_id"].startswith("attempt-")
    assert response.body["data"]["status_url"].startswith("/jobs/")


def test_a_replayed_approval_is_200_not_409() -> None:
    """Their payment may be in flight; calling it a conflict would read as failure."""
    api = Api()
    quote = api.accept().body["data"]["quote"]
    payload = {
        "quote_id": quote["quote_id"],
        "quote_hash": quote["quote_hash"],
        "quote_version": quote["quote_version"],
        "expected_purchase_version": api.version(),
    }
    first = api.api.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        body=payload,
        idempotency_key="idem-1",
        request_id=REQ,
    )
    second = api.api.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        body=payload,
        idempotency_key="idem-1",
        request_id=REQ,
    )
    assert first.status == 202
    assert second.status == 200
    assert second.body["data"]["replayed"] is True


def test_a_tampered_hash_is_409() -> None:
    api = Api()
    quote = api.accept().body["data"]["quote"]
    response = api.api.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        body={
            "quote_id": quote["quote_id"],
            "quote_hash": "f" * 64,
            "quote_version": quote["quote_version"],
            "expected_purchase_version": api.version(),
        },
        idempotency_key="idem-1",
        request_id=REQ,
    )
    assert response.status == 409
    assert response.body["error"]["code"] == "quote_hash_mismatch"


def test_an_expired_quote_is_410() -> None:
    api = Api()
    quote = api.accept().body["data"]["quote"]
    api.world.clock.advance(121)
    response = api.api.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        body={
            "quote_id": quote["quote_id"],
            "quote_hash": quote["quote_hash"],
            "quote_version": quote["quote_version"],
            "expected_purchase_version": api.version(),
        },
        idempotency_key="idem-1",
        request_id=REQ,
    )
    assert response.status == 410


def test_another_owner_gets_404() -> None:
    api = Api()
    response = api.api.read_purchase(owner_id="owner-9999", purchase_id=PURCHASE_ID, request_id=REQ)
    assert response.status == 404


# -- the fields the UI must bind to ----------------------------------------


def test_reading_a_purchase_returns_three_separate_outcomes() -> None:
    """Never merged into one status line."""
    api = Api()
    data = api.api.read_purchase(owner_id=OWNER, purchase_id=PURCHASE_ID, request_id=REQ).body[
        "data"
    ]
    assert {"payment", "order", "refund"} <= set(data)
    assert data["payment"] == "not_started"
    assert data["order"] == "not_created"
    assert data["refund"] == "none"


def test_approve_enabled_is_server_computed() -> None:
    """P1 binds the button to this, never to a countdown it runs itself."""
    api = Api()
    api.accept()
    data = api.api.read_purchase(owner_id=OWNER, purchase_id=PURCHASE_ID, request_id=REQ).body[
        "data"
    ]
    assert data["approve_enabled"] is True

    api.world.clock.advance(121)
    later = api.api.read_purchase(owner_id=OWNER, purchase_id=PURCHASE_ID, request_id=REQ).body[
        "data"
    ]
    assert later["approve_enabled"] is False


def test_every_purchase_view_carries_the_simulation_disclaimer() -> None:
    api = Api()
    data = api.api.read_purchase(owner_id=OWNER, purchase_id=PURCHASE_ID, request_id=REQ).body[
        "data"
    ]
    assert data["disclaimer"] == SIMULATION_DISCLAIMER


def test_an_owner_id_in_the_body_is_rejected() -> None:
    """The browser does not get to say who it is."""
    api = Api()
    response = api.api.accept_preparation(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        version=1,
        body={
            "diff_hash": api.diff.hash(),
            "expected_purchase_version": 1,
            "owner_id": "owner-9999",
        },
        request_id=REQ,
    )
    assert response.status == 422
    assert "token" in response.body["error"]["details"]["detail"]


# -- operator --------------------------------------------------------------


def test_a_shopper_asking_for_the_demo_controls_gets_404() -> None:
    api = Api()
    response = api.api.set_scenario(
        owner_id=OWNER, body={"scenario": "definitive_failure"}, request_id=REQ
    )
    assert response.status == 404


def test_an_operator_can_read_effect_counts() -> None:
    api = Api()
    response = api.api.effect_counts(owner_id=OPERATOR, request_id=REQ)
    assert response.status == 200
    assert "payment_effects" in response.body["data"]


# -- the contract file -----------------------------------------------------


CONTRACT = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"


def test_the_openapi_contract_exists() -> None:
    """Without it P1 cannot generate a client, and is blocked on us."""
    assert CONTRACT.exists()


@pytest.mark.parametrize(
    "path",
    [
        "/purchases",
        "/purchases/{id}",
        "/purchases/{id}/preparations/{version}/accept",
        "/purchases/{id}/approve",
        "/purchases/{id}/cancel",
        "/purchases/{id}/reconcile",
        "/purchases/{id}/case",
        "/demo/scenarios",
        "/demo/effects",
        "/callbacks/simulator",
    ],
)
def test_every_endpoint_we_own_is_in_the_contract(path: str) -> None:
    assert f"\n  {path}:" in CONTRACT.read_text(encoding="utf-8")


def test_the_contract_documents_the_approve_enabled_rule() -> None:
    """The one field P1 must not derive for themselves."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "approve_enabled" in text
    assert "countdown" in text


def test_our_endpoints_never_offer_403() -> None:
    """An inaccessible record is 404. 403 would confirm it exists."""
    # The whole document is P3's now, so the paths block is everything above
    # components. No marker to split on, and none needed.
    ours = CONTRACT.read_text(encoding="utf-8").split(chr(10) + "components:")[0]
    assert chr(34) + "403" + chr(34) not in ours


#: Keywords API Gateway and SAM reject, mirrored from WP-00's own gate in
#: scripts/check-openapi-aws-subset.mjs. Duplicated rather than imported because
#: that gate is JavaScript and additionally asserts "only /health", which is
#: true of the baseline document and deliberately not of this one.
_AWS_SUBSET_FORBIDS = (
    "nullable",
    "discriminator",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "const",
)


@pytest.mark.parametrize("keyword", _AWS_SUBSET_FORBIDS)
def test_the_contract_stays_inside_the_aws_subset(keyword: str) -> None:
    """P3's document must be mergeable into the baseline's, not just readable.

    The first draft of these endpoints used `nullable` and `allOf` freely, which
    would have parsed fine and then failed to deploy. Absence is how this
    contract says "not known"; see the Charge schema.
    """
    pattern = re.compile(rf"^\s*{re.escape(keyword)}:", re.MULTILINE)
    assert not pattern.search(CONTRACT.read_text(encoding="utf-8"))


def test_the_contract_refers_only_to_itself() -> None:
    """External $ref documents are not supported by API Gateway."""
    refs = re.findall(r"\$ref:\s*\"([^\"]+)\"", CONTRACT.read_text(encoding="utf-8"))
    assert refs, "expected the contract to use internal references"
    assert all(ref.startswith("#/") for ref in refs)


def test_every_amount_on_the_wire_carries_its_currency() -> None:
    """Money is the baseline's MoneyINR object, never a bare paise integer.

    An amount without its unit is the kind of field that reads fine until two
    services disagree about what it meant, so the contract does not offer the
    shorter form at all.
    """
    quote = Api().accept().body["data"]["quote"]
    amounts = [quote["total"]]
    amounts += [line["unit_price"] for line in quote["lines"]]
    amounts += [line["line_total"] for line in quote["lines"]]
    amounts += [c["amount"] for c in quote["charges"] if "amount" in c]

    assert amounts, "expected the quote to carry amounts"
    for amount in amounts:
        assert set(amount) == {"amount_paise", "currency"}
        assert isinstance(amount["amount_paise"], int)
        assert amount["currency"] == "INR"

    assert not [k for k in quote if k.endswith("_paise")], "no bare paise fields"


def test_an_unknown_charge_omits_the_amount_rather_than_sending_null() -> None:
    """`nullable` is not in the AWS/SAM subset, so absence carries the meaning.

    Absent means "we could not confirm this fee". It must never be read as zero.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    charge = text.split("    Charge:")[1].split("\n    QuoteLine:")[0]
    assert "nullable" not in charge
    assert "- amount" not in charge, "amount must not be a required property"


def test_the_domain_error_codes_are_documented_for_clients() -> None:
    """P3's taxonomy lives on P3's own schema, not on the shared ErrorBody.

    The shared envelope stays open to every work package; clients of these
    endpoints still get an exhaustive list, which is what stops four different
    409s collapsing into one "conflict" screen.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    assert "PurchaseErrorCode:" in text
    for code in (
        "quote_hash_mismatch",
        "approval_already_consumed",
        "purchase_already_claimed",
        "attempt_blocked_by_exposure",
        "contradictory_provider_fact",
    ):
        assert f"- {code}" in text, f"{code} is not documented"

    # The shared ErrorBody keeps its open pattern; P3 did not narrow it.
    shared = text.split("    ErrorBody:")[1].split("\n    ErrorResponse:")[0]
    assert "pattern:" in shared and "enum:" not in shared


def test_an_exact_quote_carries_no_estimated_fees_note() -> None:
    """Presence of the note is the signal, so it must be absent when exact."""
    quote = Api().accept().body["data"]["quote"]
    assert quote["amount_is_ceiling"] is False
    assert "estimated_fees_note" not in quote
